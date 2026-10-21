.PHONY: demo-deploy demo-faults demo-fault test deploy trigger-incident eval dashboard build-frontend frontend

test:
	AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing AWS_SECURITY_TOKEN=testing AWS_SESSION_TOKEN=testing AWS_DEFAULT_REGION=us-east-1 JSII_RUNTIME_PACKAGE_CACHE_ROOT=/tmp/jsii-cache PYTHONPATH=src:. python3 -m pytest -v tests/ sample_service/tests/

deploy:
	JSII_RUNTIME_PACKAGE_CACHE_ROOT=/tmp/jsii-cache PYTHONPATH=src:. python3 infra/app.py

trigger-incident:
	PYTHONPATH=src:. python3 scripts/trigger_incident.py

eval:
	PYTHONPATH=src:. python3 evals/run_evals.py

build-frontend:
	cd frontend && npm install && npm run build

frontend:
	cd frontend && npm run dev

dashboard:
	PYTHONPATH=src:. python3 -m uvicorn dashboard.app:dashboard_app --host 0.0.0.0 --port 8000

# --- Hackathon demo: break the sample service on purpose ------------------
# make demo-deploy                      deploy sample service + OpsPilot pipeline
# make demo-faults                      list planted faults
# make demo-fault SCENARIO=orders       orders|checkout|inventory|payments|reports
demo-deploy:
	JSII_RUNTIME_PACKAGE_CACHE_ROOT=/tmp/jsii-cache PYTHONPATH=src:. npx -y aws-cdk@2 deploy --all --require-approval never

demo-faults:
	python3 scripts/demo_faults.py list

demo-fault:
	python3 scripts/demo_faults.py $(SCENARIO) --watch
