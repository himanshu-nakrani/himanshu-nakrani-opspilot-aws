.PHONY: test deploy trigger-incident eval dashboard

test:
	AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing AWS_SECURITY_TOKEN=testing AWS_SESSION_TOKEN=testing AWS_DEFAULT_REGION=us-east-1 JSII_RUNTIME_PACKAGE_CACHE_ROOT=/tmp/jsii-cache PYTHONPATH=src:. python3 -m pytest -v tests/ sample_service/tests/

deploy:
	JSII_RUNTIME_PACKAGE_CACHE_ROOT=/tmp/jsii-cache PYTHONPATH=src:. python3 infra/app.py

trigger-incident:
	PYTHONPATH=src:. python3 scripts/trigger_incident.py

eval:
	PYTHONPATH=src:. python3 evals/run_evals.py

dashboard:
	PYTHONPATH=src:. python3 -m uvicorn dashboard.app:dashboard_app --host 0.0.0.0 --port 8000
