.PHONY: up down help

help: ## show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

up: ## start the sentinel fleet
	@ids=$$(aws ec2 describe-instances \
	  --filters Name=tag:Project,Values=sentinel Name=instance-state-name,Values=stopped \
	  --query 'Reservations[].Instances[].InstanceId' --output text); \
	if [ -z "$$ids" ]; then echo "up: no stopped sentinel instances"; \
	else aws ec2 start-instances --instance-ids $$ids; fi

down: ## stop the sentinel fleet
	@ids=$$(aws ec2 describe-instances \
	  --filters Name=tag:Project,Values=sentinel Name=instance-state-name,Values=running \
	  --query 'Reservations[].Instances[].InstanceId' --output text); \
	if [ -z "$$ids" ]; then echo "down: no running sentinel instances (fleet is cold)"; \
	else aws ec2 stop-instances --instance-ids $$ids; fi
