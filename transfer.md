# run form ec2

1. checkpoint 1

```bash
cd ~/himanshu-nakrani-opspilot-aws
nohup bash scripts/deploy.sh checkpoint1 > /tmp/checkpoint1.log 2>&1 &
```

2. main app

```bash
cd ~/himanshu-nakrani-opspilot-aws
. .venv/bin/activate
nohup bash scripts/deploy.sh dashboard > /tmp/dashboard.log 2>&1 &
```
