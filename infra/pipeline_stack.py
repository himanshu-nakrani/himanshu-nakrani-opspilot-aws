"""OpsPilot Pipeline Stack: Step Functions orchestration, Lambdas, CodeBuild verification, and EventBridge trigger."""

import json
import os
import re
from pathlib import Path
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
    aws_codebuild as codebuild,
    aws_stepfunctions as sfn,
    aws_sqs as sqs,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
)
from constructs import Construct

from infra.core_stack import CoreStack
from infra.bundling import python_lambda_code
from infra.sample_service_stack import ALARM_PREFIX, SampleServiceStack


class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        core_stack: CoreStack,
        sample_service_stack: SampleServiceStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bedrock_model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
        github_repo = os.environ.get("GITHUB_REPO", "himanshu-nakrani/opspilot-aws")
        jira_base_url = os.environ.get("JIRA_BASE_URL", "https://jira.example.com")
        jira_project_key = os.environ.get("JIRA_PROJECT_KEY", "OPS")
        jira_email = os.environ.get("JIRA_EMAIL", "opspilot@example.com")

        common_env = {
            "INCIDENTS_TABLE_NAME": core_stack.incidents_table.table_name,
            "GITHUB_REPO": github_repo,
            "BEDROCK_MODEL_ID": bedrock_model_id,
            "STRANDS_FRAMEWORK": "strands-agents",
            "AGENTCORE_RUNTIME_ENABLED": "true",
            "AGENTCORE_POLICY_ENFORCEMENT": "strict",
            "JIRA_BASE_URL": jira_base_url,
            "JIRA_PROJECT_KEY": jira_project_key,
            "JIRA_EMAIL": jira_email,
            "JIRA_SECRET_ARN": core_stack.jira_secret.secret_arn,
            "GITHUB_SECRET_ARN": core_stack.github_secret.secret_arn,
            "SLACK_SECRET_ARN": core_stack.slack_secret.secret_arn,
            "SNS_TOPIC_ARN": core_stack.alerts_topic.topic_arn,
            # Explicit live mode: real Bedrock/GitHub/Jira, failures raise to Step Functions.
            "OPSPILOT_MODE": "live",
        }

        # Every Lambda shares one bundled asset: src/opspilot plus requirements-lambda.txt
        # installed into the package root. Without this, the functions import-fail at
        # cold start (pydantic, httpx, strands-agents are not in the Lambda runtime).
        repo_root = str(Path(__file__).resolve().parent.parent)
        lambda_code = python_lambda_code(
            repo_root,
            requirements="requirements-lambda.txt",
            copies=[("src/opspilot", "opspilot")],
            include=["src"],
        )

        # 1. CollectContext Function
        self.collect_context_fn = lambda_.Function(
            self,
            "CollectContextFunction",
            function_name="opspilot-collect-context",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="opspilot.collect_context.handler",
            code=lambda_code,
            timeout=Duration.seconds(60),
            memory_size=512,
            environment=common_env,
        )
        core_stack.incidents_table.grant_read_write_data(self.collect_context_fn)
        sample_service_stack.log_group.grant(self.collect_context_fn, "logs:FilterLogEvents", "logs:StartQuery", "logs:GetQueryResults")

        # 2. RunRCA Function (Least privilege: invoke only configured Bedrock model)
        self.run_rca_fn = lambda_.Function(
            self,
            "RunRcaFunction",
            function_name="opspilot-run-rca",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="opspilot.rca.agent.handler",
            code=lambda_code,
            timeout=Duration.minutes(3),
            memory_size=1024,
            environment=common_env,
        )
        core_stack.incidents_table.grant_read_write_data(self.run_rca_fn)
        self.run_rca_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=self._bedrock_model_arns(bedrock_model_id),
            )
        )

        # 3. CreateTicket Function
        self.create_ticket_fn = lambda_.Function(
            self,
            "CreateTicketFunction",
            function_name="opspilot-create-ticket",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="opspilot.jira_client.handler",
            code=lambda_code,
            timeout=Duration.seconds(60),
            memory_size=256,
            environment=common_env,
        )
        core_stack.incidents_table.grant_read_write_data(self.create_ticket_fn)
        core_stack.jira_secret.grant_read(self.create_ticket_fn)

        # 4. ProposeFix Function
        self.propose_fix_fn = lambda_.Function(
            self,
            "ProposeFixFunction",
            function_name="opspilot-propose-fix",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="opspilot.fix.agent.handler",
            code=lambda_code,
            timeout=Duration.minutes(5),
            memory_size=1024,
            environment=common_env,
        )
        core_stack.incidents_table.grant_read_write_data(self.propose_fix_fn)
        core_stack.github_secret.grant_read(self.propose_fix_fn)
        # ProposeFix does not call Bedrock today (stub generator); grant it when a real patch agent lands.

        # 5. MarkNeedsHuman Function
        self.mark_needs_human_fn = lambda_.Function(
            self,
            "MarkNeedsHumanFunction",
            function_name="opspilot-mark-needs-human",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="opspilot.fix.agent.mark_needs_human_handler",
            code=lambda_code,
            timeout=Duration.seconds(60),
            memory_size=256,
            environment=common_env,
        )
        core_stack.incidents_table.grant_read_write_data(self.mark_needs_human_fn)
        core_stack.github_secret.grant_read(self.mark_needs_human_fn)

        # 6. Notify Function
        self.notify_fn = lambda_.Function(
            self,
            "NotifyFunction",
            function_name="opspilot-notify",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="opspilot.notify.handler",
            code=lambda_code,
            timeout=Duration.seconds(60),
            memory_size=256,
            environment=common_env,
        )
        core_stack.incidents_table.grant_read_write_data(self.notify_fn)
        core_stack.slack_secret.grant_read(self.notify_fn)
        core_stack.alerts_topic.grant_publish(self.notify_fn)

        # 7. CodeBuild Verify Project
        owner, repo_name = github_repo.split("/", 1) if "/" in github_repo else ("himanshu-nakrani", "opspilot-aws")
        self.verify_project = codebuild.Project(
            self,
            "VerifyProject",
            project_name="opspilot-verify-fix",
            description="Two-phase verification: repro test must fail on base and pass on fix branch",
            source=codebuild.Source.git_hub(
                owner=owner,
                repo=repo_name,
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.SMALL,
            ),
            build_spec=codebuild.BuildSpec.from_source_filename("src/opspilot/verify/buildspec.yml"),
        )

        # 7b. ParseVerification Function: CodeBuild Build -> VerificationResult
        self.parse_verification_fn = lambda_.Function(
            self,
            "ParseVerificationFunction",
            function_name="opspilot-parse-verification",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="opspilot.verify.runner.parse_verification_handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment=common_env,
        )
        self.parse_verification_fn.add_to_role_policy(
            iam.PolicyStatement(actions=["codebuild:BatchGetBuilds"], resources=[self.verify_project.project_arn])
        )

        # 8. Step Functions State Machine (from statemachine/opspilot.asl.json)
        asl_path = Path(__file__).resolve().parent.parent / "statemachine" / "opspilot.asl.json"
        with open(asl_path, "r", encoding="utf-8") as f:
            asl_template = f.read()

        asl_rendered = asl_template.replace("${CollectContextFnArn}", self.collect_context_fn.function_arn)
        asl_rendered = asl_rendered.replace("${RunRcaFnArn}", self.run_rca_fn.function_arn)
        asl_rendered = asl_rendered.replace("${CreateTicketFnArn}", self.create_ticket_fn.function_arn)
        asl_rendered = asl_rendered.replace("${ProposeFixFnArn}", self.propose_fix_fn.function_arn)
        asl_rendered = asl_rendered.replace("${VerifyProjectName}", self.verify_project.project_name)
        asl_rendered = asl_rendered.replace("${MarkNeedsHumanFnArn}", self.mark_needs_human_fn.function_arn)
        asl_rendered = asl_rendered.replace("${NotifyFnArn}", self.notify_fn.function_arn)
        asl_rendered = asl_rendered.replace("${ParseVerificationFnArn}", self.parse_verification_fn.function_arn)
        if re.search(r"\$\{[A-Za-z]+(?:FnArn|ProjectName)\}", asl_rendered):
            raise ValueError("Unsubstituted placeholder left in statemachine/opspilot.asl.json")

        self.state_machine = sfn.CfnStateMachine(
            self,
            "OpsPilotStateMachine",
            state_machine_name="opspilot",
            definition_string=asl_rendered,
            role_arn=self._create_state_machine_role().role_arn,
        )

        # 9. Ingest Function (triggers State Machine with deduplication)
        ingest_env = dict(common_env)
        ingest_env["STATE_MACHINE_ARN"] = self.state_machine.ref
        ingest_env["SERVICE_NAME"] = "sample-service"
        ingest_env["LOG_GROUP_NAME"] = sample_service_stack.log_group.log_group_name

        self.ingest_fn = lambda_.Function(
            self,
            "IngestFunction",
            function_name="opspilot-ingest",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="opspilot.ingest.handle_alarm_event",
            code=lambda_code,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment=ingest_env,
        )
        core_stack.incidents_table.grant_read_write_data(self.ingest_fn)
        self.ingest_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution"],
                resources=[self.state_machine.ref],
            )
        )

        # 10. EventBridge Rule: CloudWatch Alarm -> Ingest Function
        self.alarm_rule = events.Rule(
            self,
            "AlarmToOpsPilotRule",
            rule_name="opspilot-alarm-trigger",
            description="Routes CloudWatch Alarm State Change events to OpsPilot Ingest Lambda",
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={
                    # Every sample-service alarm (one per planted fault) shares this prefix.
                    "alarmName": [{"prefix": ALARM_PREFIX}],
                    "state": {
                        "value": ["ALARM"],
                    },
                },
            ),
        )
        self.ingest_dlq = sqs.Queue(self, "IngestDlq", queue_name="opspilot-ingest-dlq",
                                    retention_period=Duration.days(14))
        self.alarm_rule.add_target(
            targets.LambdaFunction(
                self.ingest_fn,
                dead_letter_queue=self.ingest_dlq,
                retry_attempts=4,
                max_event_age=Duration.hours(2),
            )
        )

        # Page a human if the pipeline itself fails (including NotifyFailed).
        cloudwatch.Alarm(
            self,
            "PipelineExecutionsFailedAlarm",
            alarm_name="opspilot-executions-failed",
            metric=cloudwatch.Metric(
                namespace="AWS/States",
                metric_name="ExecutionsFailed",
                dimensions_map={"StateMachineArn": self.state_machine.ref},
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(cw_actions.SnsAction(core_stack.alerts_topic))

    def _bedrock_model_arns(self, model_id: str) -> list:
        """Scope Bedrock to the configured model (and its cross-region inference profile)."""
        arns = [f"arn:aws:bedrock:*::foundation-model/{model_id.split('.', 1)[1] if model_id.split('.', 1)[0] in ('us', 'eu', 'apac', 'global') else model_id}"]
        if model_id.split(".", 1)[0] in ("us", "eu", "apac", "global"):
            arns.append(f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{model_id}")
        return arns

    def _create_state_machine_role(self) -> iam.Role:
        role = iam.Role(
            self,
            "OpsPilotSfnExecutionRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
        )
        fns = [self.collect_context_fn, self.run_rca_fn, self.create_ticket_fn, self.propose_fix_fn,
               self.parse_verification_fn, self.mark_needs_human_fn, self.notify_fn]
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[f.function_arn for f in fns] + [f"{f.function_arn}:*" for f in fns],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["codebuild:StartBuild", "codebuild:StopBuild", "codebuild:BatchGetBuilds"],
                resources=[self.verify_project.project_arn],
            )
        )
        # Managed rule Step Functions creates for codebuild:startBuild.sync
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["events:PutTargets", "events:PutRule", "events:DescribeRule"],
                resources=[
                    f"arn:aws:events:{self.region}:{self.account}:rule/StepFunctionsGetEventsForCodeBuildStartBuildRule"
                ],
            )
        )
        return role
