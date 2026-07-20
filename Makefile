.PHONY: up down help fault heal

# ansible-playbook on macOS needs this or forked workers crash (Objective-C
# runtime is fork-hostile); harmless on Linux/ctrl-1.
ANSIBLE := OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES ansible-playbook

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

fault: ## inject a fault: make fault F=<label>  (payments_latency|db_conn_leak|bad_deploy|container_oom|config_drift)
	@test -n "$(F)" || { echo "usage: make fault F=<label>"; exit 1; }
	@cd ansible && $(ANSIBLE) ../faults/inject.yml -e fault=$(F)

heal: ## run the matching remediation for a fault: make heal F=<label>
	@test -n "$(F)" || { echo "usage: make heal F=<label>"; exit 1; }
	@cd ansible && case "$(F)" in \
	  payments_latency) $(ANSIBLE) playbooks/fix_config.yml -e service=payments-service ;; \
	  db_conn_leak)     $(ANSIBLE) playbooks/restart_container.yml -e service=orders-service ;; \
	  bad_deploy)       $(ANSIBLE) playbooks/rollback_deploy.yml -e service=payments-service ;; \
	  container_oom)    $(ANSIBLE) playbooks/restart_container.yml -e service=checkout-worker ;; \
	  config_drift)     $(ANSIBLE) playbooks/fix_config.yml -e service=api-gateway ;; \
	  *) echo "unknown fault: $(F)"; exit 1 ;; \
	esac
