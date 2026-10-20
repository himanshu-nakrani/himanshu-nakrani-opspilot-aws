"""OpsPilot CDK App entrypoint."""

import os
import aws_cdk as cdk
from infra.core_stack import CoreStack
from infra.sample_service_stack import SampleServiceStack
from infra.pipeline_stack import PipelineStack

app = cdk.App()

account = os.environ.get("CDK_DEFAULT_ACCOUNT", "123456789012")
region = os.environ.get("CDK_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))
env = cdk.Environment(account=account, region=region)

core = CoreStack(app, "OpsPilotCoreStack", env=env)
sample = SampleServiceStack(app, "OpsPilotSampleServiceStack", env=env)
pipeline = PipelineStack(app, "OpsPilotPipelineStack", core_stack=core, sample_service_stack=sample, env=env)

app.synth()
