"""Delivery path for the demo storefront.

CodeCommit holds the app. CodePipeline runs CodeBuild (publish a Lambda
version) and CodeDeploy (shift the live alias). OpsPilot's alarms stay on the
same function, and its fix pull requests target this repository, so a merged
fix is what the next pipeline run deploys.
"""

import os
import shutil

import aws_cdk as cdk
import jsii
from aws_cdk import (
    CustomResource,
    Duration,
    Stack,
    aws_codebuild as codebuild,
    aws_codecommit as codecommit,
    aws_codedeploy as codedeploy,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as actions,
    aws_iam as iam,
    aws_lambda as lambda_,
    custom_resources as cr,
)
APP_REPO_NAME = "opspilot-sample-service"
ALIAS_NAME = "live"
PIPELINE_NAME = "opspilot-sample-service"

_MONOREPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SEED_FILES = (
    "sample_service/__init__.py",
    "sample_service/app.py",
    "sample_service/faults.py",
    "sample_service/requirements.txt",
    "sample_service/tests/__init__.py",
    "sample_service/tests/test_app.py",
    "sample_service/tests/test_faults.py",
)


@jsii.implements(cdk.ILocalBundling)
class _SeedBundle:
    def try_bundle(self, output_dir: str, _options) -> bool:
        shutil.copy(os.path.join(_MONOREPO, "infra/app_repo_seed/handler.py"), os.path.join(output_dir, "handler.py"))
        repo_dir = os.path.join(output_dir, "repo")
        for rel in _SEED_FILES:
            dest = os.path.join(repo_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(os.path.join(_MONOREPO, rel), dest)
        spec = os.path.join(repo_dir, "buildspec.yml")
        shutil.copy(os.path.join(_MONOREPO, "sample_service/ci/buildspec.yml"), spec)
        return True


def attach_app_delivery(stack: Stack, service_fn: lambda_.Function) -> None:
    """Create the app repo, seed main, and the pipeline that deploys it."""
    repo = codecommit.Repository(
        stack,
        "AppSourceRepo",
        repository_name=APP_REPO_NAME,
        description="Demo storefront source. CodePipeline deploys main; OpsPilot opens fix pull requests here.",
    )
    repo.apply_removal_policy(cdk.RemovalPolicy.RETAIN)
    stack.app_repo = repo

    # Alias is what the public URL and CodeDeploy both move. CDK owns the initial
    # version; later pipeline runs move the alias outside CloudFormation.
    live = lambda_.Alias(stack, "LiveAlias", alias_name=ALIAS_NAME, version=service_fn.current_version)
    stack.function_url = live.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

    seed_fn = lambda_.Function(
        stack,
        "SeedAppRepoFunction",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="handler.on_event",
        timeout=Duration.minutes(1),
        code=lambda_.Code.from_asset(
            _MONOREPO,
            exclude=["*"],
            bundling=cdk.BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                local=_SeedBundle(),
                command=["bash", "-c", "echo seed bundle is local-only && exit 1"],
            ),
        ),
    )
    repo.grant(seed_fn, "codecommit:GetBranch", "codecommit:CreateCommit", "codecommit:GetCommit")
    seed = CustomResource(
        stack,
        "SeedAppRepoMain",
        service_token=cr.Provider(stack, "SeedAppRepoProvider", on_event_handler=seed_fn).service_token,
        properties={"RepoName": repo.repository_name},
    )
    application = codedeploy.LambdaApplication(stack, "AppDeployApplication", application_name=APP_REPO_NAME)
    deployment_group = codedeploy.LambdaDeploymentGroup(
        stack,
        "AppDeploymentGroup",
        application=application,
        alias=live,
        deployment_group_name=f"{APP_REPO_NAME}-live",
        deployment_config=codedeploy.LambdaDeploymentConfig.ALL_AT_ONCE,
        auto_rollback=codedeploy.AutoRollbackConfig(failed_deployment=True),
    )

    build = codebuild.PipelineProject(
        stack,
        "AppBuild",
        project_name=f"{APP_REPO_NAME}-build",
        description="Package the storefront, publish a Lambda version, and emit the CodeDeploy AppSpec",
        timeout=Duration.minutes(10),
        environment=codebuild.BuildEnvironment(
            build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
            compute_type=codebuild.ComputeType.SMALL,
            environment_variables={
                "FUNCTION_NAME": codebuild.BuildEnvironmentVariable(value=service_fn.function_name),
                "ALIAS_NAME": codebuild.BuildEnvironmentVariable(value=ALIAS_NAME),
            },
        ),
        build_spec=codebuild.BuildSpec.from_source_filename("buildspec.yml"),
    )
    build.add_to_role_policy(
        iam.PolicyStatement(
            actions=[
                "lambda:GetFunction",
                "lambda:GetFunctionConfiguration",
                "lambda:UpdateFunctionCode",
                "lambda:PublishVersion",
                "lambda:GetAlias",
            ],
            resources=[service_fn.function_arn, f"{service_fn.function_arn}:*"],
        )
    )
    build.add_to_role_policy(
        iam.PolicyStatement(
            actions=["lambda:GetAlias"],
            resources=[live.function_arn],
        )
    )

    source_output = codepipeline.Artifact("SourceOutput")
    build_output = codepipeline.Artifact("BuildOutput")
    pipeline = codepipeline.Pipeline(
        stack,
        "AppPipeline",
        pipeline_name=PIPELINE_NAME,
        # restart_execution_on_update is V1-only; pin the type so CDK stops warning
        # about the implicit default (behavior identical to before).
        pipeline_type=codepipeline.PipelineType.V1,
        restart_execution_on_update=True,
    )
    pipeline.add_stage(
        stage_name="Source",
        actions=[
            actions.CodeCommitSourceAction(
                action_name="Source",
                repository=repo,
                branch="main",
                output=source_output,
                trigger=actions.CodeCommitTrigger.EVENTS,
            )
        ],
    )
    pipeline.add_stage(
        stage_name="Build",
        actions=[
            actions.CodeBuildAction(
                action_name="Build",
                project=build,
                input=source_output,
                outputs=[build_output],
            )
        ],
    )
    pipeline.node.add_dependency(seed)
    _add_codedeploy_stage(pipeline, application, deployment_group)
    pipeline.artifact_bucket.grant_read(deployment_group.role)

    cdk.CfnOutput(stack, "AppCodeCommitRepoName", value=repo.repository_name)
    cdk.CfnOutput(stack, "AppCodeCommitCloneUrlHttp", value=repo.repository_clone_url_http)
    cdk.CfnOutput(stack, "AppPipelineName", value=pipeline.pipeline_name)


def _add_codedeploy_stage(pipeline: codepipeline.Pipeline, application, deployment_group) -> None:
    """CodePipeline's CodeDeploy action has no Lambda L2. Append the stage on the L1."""
    pipeline.role.add_to_policy(
        iam.PolicyStatement(
            actions=[
                "codedeploy:CreateDeployment",
                "codedeploy:GetDeployment",
                "codedeploy:GetDeploymentConfig",
                "codedeploy:GetApplication",
                "codedeploy:GetApplicationRevision",
                "codedeploy:RegisterApplicationRevision",
            ],
            resources=["*"],
        )
    )
    cfn = pipeline.node.default_child
    cfn.add_property_override("Stages.2", {
        "Name": "Deploy",
        "Actions": [{
            "Name": "Deploy",
            "ActionTypeId": {"Category": "Deploy", "Owner": "AWS", "Provider": "CodeDeploy", "Version": "1"},
            "Configuration": {
                "ApplicationName": application.application_name,
                "DeploymentGroupName": deployment_group.deployment_group_name,
            },
            "InputArtifacts": [{"Name": "BuildOutput"}],
            "RunOrder": 1,
        }],
    })
