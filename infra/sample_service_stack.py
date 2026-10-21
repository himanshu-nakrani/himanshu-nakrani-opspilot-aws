"""OpsPilot Sample Service Stack: the demo storefront OpsPilot monitors.

FastAPI on Lambda behind a public Function URL, one log group, and one
CloudWatch alarm per planted fault (see sample_service/faults.py). Every alarm
name starts with ``ALARM_PREFIX``; the pipeline's EventBridge rule matches that
prefix, so each fault opens its own OpsPilot incident (dedup is per alarm name).
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_cloudwatch as cloudwatch,
    RemovalPolicy,
)
from constructs import Construct

from infra.bundling import python_lambda_code

ALARM_PREFIX = "OpsPilotSampleService"
METRIC_NAMESPACE = "OpsPilot/SampleService"

# component -> alarm name. "orders" keeps the original alarm name the dashboard,
# fixtures and tests already use.
ERROR_ALARMS = {
    "orders": "OpsPilotSampleServiceErrors",
    "checkout": f"{ALARM_PREFIX}-CheckoutErrors",
    "inventory": f"{ALARM_PREFIX}-InventoryDbTimeouts",
}
LATENCY_ALARM = f"{ALARM_PREFIX}-LatencyP95"
CRASH_ALARM = f"{ALARM_PREFIX}-Crashes"
LATENCY_THRESHOLD_MS = 3000


class SampleServiceStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        repo_root = str(Path(__file__).resolve().parent.parent)

        self.log_group = logs.LogGroup(
            self,
            "SampleServiceLogGroup",
            log_group_name="/aws/lambda/opspilot-sample-service",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # fastapi + mangum are not in the Lambda runtime, so they are bundled.
        self.service_fn = lambda_.Function(
            self,
            "SampleServiceFunction",
            function_name="opspilot-sample-service",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="sample_service.app.handler",
            code=python_lambda_code(
                repo_root,
                requirements="sample_service/requirements.txt",
                copies=[("sample_service", "sample_service")],
                include=["sample_service"],
            ),
            timeout=Duration.seconds(30),
            memory_size=256,  # the /reports/export?days=90 fault relies on this ceiling
            log_group=self.log_group,
            environment={"ENV": "demo"},
        )

        # Public URL so the demo can hit the service with curl. It only serves the
        # demo storefront; each request costs a few ms of a 256 MB Lambda.
        self.function_url = self.service_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        self.alarms: dict = {}
        error_metrics = {}
        for component, alarm_name in ERROR_ALARMS.items():
            mf = logs.MetricFilter(
                self,
                f"{component.capitalize()}ErrorFilter",
                log_group=self.log_group,
                metric_namespace=METRIC_NAMESPACE,
                metric_name=f"{component.capitalize()}Errors",
                filter_pattern=logs.FilterPattern.all(
                    logs.FilterPattern.string_value("$.event", "=", "unhandled_exception"),
                    logs.FilterPattern.string_value("$.component", "=", component),
                ),
                metric_value="1",
                default_value=0,
            )
            metric = mf.metric(statistic="Sum", period=Duration.minutes(1))
            error_metrics[component] = metric
            self.alarms[component] = self._alarm(
                # Keep the original construct ID for orders so an already-deployed stack updates in place
                # (its alarm name OpsPilotSampleServiceErrors is unchanged).
                "SampleServiceErrorAlarm" if component == "orders" else f"{component.capitalize()}ErrorAlarm",
                alarm_name, metric, 1,
                f"Unhandled exceptions in the {component} component of the sample service",
            )
        # Back-compat handle for code that expects a single alarm.
        self.alarm = self.alarms["orders"]

        duration_p95 = self.service_fn.metric_duration(statistic="p95", period=Duration.minutes(1))
        self.alarms["latency"] = self._alarm(
            "LatencyAlarm", LATENCY_ALARM, duration_p95, LATENCY_THRESHOLD_MS,
            f"Sample service p95 latency above {LATENCY_THRESHOLD_MS} ms",
        )
        # Lambda-level errors: OOM kills, timeouts, init crashes (handled 500s do not count).
        lambda_errors = self.service_fn.metric_errors(statistic="Sum", period=Duration.minutes(1))
        self.alarms["crashes"] = self._alarm(
            "CrashAlarm", CRASH_ALARM, lambda_errors, 1,
            "Sample service Lambda invocations crashed (out of memory, timeout or runtime exit)",
        )

        request_count = logs.MetricFilter(
            self,
            "RequestFilter",
            log_group=self.log_group,
            metric_namespace=METRIC_NAMESPACE,
            metric_name="Requests",
            filter_pattern=logs.FilterPattern.string_value("$.event", "=", "request"),
            metric_value="1",
            default_value=0,
        ).metric(statistic="Sum", period=Duration.minutes(1))

        dashboard = cloudwatch.Dashboard(self, "SampleServiceDashboard", dashboard_name="OpsPilot-SampleService")
        dashboard.add_widgets(
            cloudwatch.AlarmStatusWidget(title="OpsPilot-monitored alarms", alarms=list(self.alarms.values()), width=24),
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(title="Requests vs unhandled errors (per min)",
                                   left=[request_count], right=list(error_metrics.values()), width=12),
            cloudwatch.GraphWidget(title="Latency p95 (ms) and Lambda crashes",
                                   left=[duration_p95], right=[lambda_errors], width=12),
        )
        dashboard.add_widgets(
            cloudwatch.LogQueryWidget(
                title="Recent unhandled exceptions",
                log_group_names=[self.log_group.log_group_name],
                query_lines=[
                    "fields @timestamp, component, path, error_type, error_message",
                    "filter event = 'unhandled_exception'",
                    "sort @timestamp desc",
                    "limit 20",
                ],
                width=24,
            ),
        )

        CfnOutput(self, "SampleServiceUrl", value=self.function_url.url, export_name="OpsPilotSampleServiceUrl")
        CfnOutput(self, "SampleServiceDashboardName", value="OpsPilot-SampleService")

    def _alarm(self, cid: str, name: str, metric: cloudwatch.IMetric, threshold: float, description: str):
        return cloudwatch.Alarm(
            self,
            cid,
            alarm_name=name,
            alarm_description=description,
            metric=metric,
            threshold=threshold,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
