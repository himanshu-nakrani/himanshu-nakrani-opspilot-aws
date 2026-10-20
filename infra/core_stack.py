"""OpsPilot Core Stack: DynamoDB incidents table, Secrets Manager secrets, and SNS topic."""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
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

        self.github_secret = secretsmanager.Secret(
            self,
            "GitHubTokenSecret",
            secret_name="opspilot/github",
            description="OpsPilot fine-grained GitHub PAT",
        )

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
