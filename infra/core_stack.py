"""OpsPilot Core Stack: DynamoDB incidents table, CodeCommit source repo, Secrets Manager secrets, SNS topic."""

import os

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_codecommit as codecommit,
    aws_dynamodb as dynamodb,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
    RemovalPolicy,
)
from constructs import Construct


class CoreStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DynamoDB table for incidents audit trail and dedup
        self.incidents_table = dynamodb.Table(
            self,
            "OpspilotIncidentsTable",
            table_name="opspilot-incidents",
            partition_key=dynamodb.Attribute(
                name="incident_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Secrets Manager references for 3rd-party services
        self.jira_secret = secretsmanager.Secret(
            self,
            "JiraCredentialsSecret",
            secret_name="opspilot/jira",
            description="OpsPilot Jira API token and credentials",
        )

        # AWS CodeCommit repository OpsPilot reads source from, branches, and opens fix PRs in.
        # IAM-only (no external tokens). RETAIN so `destroy` never deletes fix history; when the
        # repo already exists (re-deploy after destroy, or pre-provisioned by the event team)
        # scripts/deploy.sh sets CODECOMMIT_REPO_EXISTS=1 and we import it instead.
        repo_name = os.environ.get("CODECOMMIT_REPO", "opspilot-aws")
        if os.environ.get("CODECOMMIT_REPO_EXISTS") == "1":
            self.source_repo = codecommit.Repository.from_repository_name(self, "OpspilotSourceRepo", repo_name)
        else:
            repo = codecommit.Repository(
                self,
                "OpspilotSourceRepo",
                repository_name=repo_name,
                description="OpsPilot source + demo service; OpsPilot opens fix PRs here",
            )
            repo.apply_removal_policy(RemovalPolicy.RETAIN)
            self.source_repo = repo
        cdk.CfnOutput(self, "CodeCommitRepoName", value=self.source_repo.repository_name)
        cdk.CfnOutput(self, "CodeCommitCloneUrlHttp", value=self.source_repo.repository_clone_url_http)

        self.slack_secret = secretsmanager.Secret(
            self,
            "SlackWebhookSecret",
            secret_name="opspilot/slack",
            description="OpsPilot Slack incoming webhook URL",
        )

        # SNS notification topic
        self.alerts_topic = sns.Topic(
            self,
            "OpspilotAlertsTopic",
            topic_name="opspilot-alerts",
            display_name="OpsPilot Alerts and Incident Notifications",
        )
