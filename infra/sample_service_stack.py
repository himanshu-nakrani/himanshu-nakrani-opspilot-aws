"""OpsPilot Sample Service Stack: FastAPI on Lambda, CloudWatch Log Group, Metric Filter, and Alarm."""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_cloudwatch as cloudwatch,
    RemovalPolicy,
)
from constructs import Construct


class SampleServiceStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Dedicated Log Group with retention
        self.log_group = logs.LogGroup(
            self,
            "SampleServiceLogGroup",
            log_group_name="/aws/lambda/opspilot-sample-service",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Sample Service Lambda Function (Python 3.12, Mangum)
        self.service_fn = lambda_.Function(
            self,
            "SampleServiceFunction",
            function_name="opspilot-sample-service",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="sample_service.app.handler",
            code=lambda_.Code.from_asset(
                ".",
                exclude=[".git", ".pytest_cache", ".venv", "cdk.out", ".runs", ".threads", "evals"],
            ),
            timeout=Duration.seconds(30),
            memory_size=256,
            log_group=self.log_group,
            environment={
                "ENV": "poc",
            },
        )

        # Metric Filter: matches ERROR or Traceback in logs
        self.metric_filter = logs.MetricFilter(
            self,
            "SampleServiceErrorFilter",
            log_group=self.log_group,
            metric_namespace="OpsPilot",
            metric_name="SampleServiceErrors",
            filter_pattern=logs.FilterPattern.any_term("ERROR", "Traceback"),
            metric_value="1",
            default_value=0,
        )

        # CloudWatch Alarm: triggers when errors occur
        self.alarm = cloudwatch.Alarm(
            self,
            "SampleServiceErrorAlarm",
            alarm_name="OpsPilotSampleServiceErrors",
            alarm_description="Triggers when sample service encounters unhandled errors or tracebacks",
            metric=self.metric_filter.metric(
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
