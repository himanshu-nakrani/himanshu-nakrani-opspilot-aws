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


def should_import_codecommit_repo() -> bool:
    """True only when the operator set CODECOMMIT_REPO_EXISTS to the string 1.

    scripts/deploy.sh defaults an unset value to 0 and does not turn this on
    because the repository already exists. Importing drops the owned resource
    from CoreStack and detaches the repo.
    """
    return os.environ.get("CODECOMMIT_REPO_EXISTS") == "1"


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

        # Ticketing is native AWS Systems Manager OpsCenter (IAM only); nothing reads this secret now.
        # DEPRECATED, kept for ONE release: stacks deployed before the OpsCenter switch have
        # OpsPilotPipelineStack importing this secret's ARN. Deleting the secret (and so its export)
        # in the same deploy fails: CloudFormation updates this stack first and refuses to drop an
        # export that is still imported. This release keeps the secret and pins its export while the
        # pipeline stops importing it; remove both in the next release.
        self.jira_secret = secretsmanager.Secret(
            self,
            "JiraCredentialsSecret",
            secret_name="opspilot/jira",
            description="DEPRECATED (unused since OpsCenter ticketing); remove next release",
        )
        self.export_value(self.jira_secret.secret_arn)

        # DEPRECATED, kept for ONE release for the same reason as the Jira secret: stacks deployed
        # before the CodeCommit switch have OpsPilotPipelineStack importing this secret's ARN.
        self.github_secret = secretsmanager.Secret(
            self,
            "GitHubTokenSecret",
            secret_name="opspilot/github",
            description="DEPRECATED (unused since CodeCommit source control); remove next release",
        )
        self.export_value(self.github_secret.secret_arn)

        # AWS CodeCommit repository OpsPilot reads source from, branches, and opens fix PRs in.
        # IAM-only (no external tokens). RETAIN so `destroy` never deletes fix history.
        # Own the repository here unless the operator explicitly asked to import it.
        repo_name = os.environ.get("CODECOMMIT_REPO", "opspilot-aws")
        if should_import_codecommit_repo():
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
        # The pipeline now imports the storefront repo instead of this one. These exports stay
        # for one release: this stack updates first, and CloudFormation will not drop an export
        # the previous pipeline template still imports.
        self.export_value(self.source_repo.repository_arn)
        self.export_value(self.source_repo.repository_name)
        self.export_value(self.source_repo.repository_clone_url_http)
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
