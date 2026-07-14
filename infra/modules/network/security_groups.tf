# Security groups — a stateful firewall per host role. Rules are written as
# standalone aws_vpc_security_group_(ingress|egress)_rule resources (not inline
# blocks) so that (a) SGs can reference each other without dependency cycles and
# (b) each rule maps 1:1 to a row in the reviewed matrix below.
#
# IMPORTANT: an SG with no egress rule has its AWS-default allow-all egress
# STRIPPED by Terraform, so each SG gets an explicit allow-all egress rule
# (hosts need outbound for GHCR pulls, Bedrock, and package installs).
#
# Reviewed matrix (Option A: only Grafana is browser-reachable; raw
# Prometheus/Alertmanager/Tempo reached via SSH tunnel through ctrl-1):
#
#   sg-ctrl  8080 <- sg-mon, admin | 3001 <- admin | 22 <- admin
#   sg-app   8000-8003 <- sg-app, sg-ctrl, sg-mon | 8000 <- 0.0.0.0/0
#            9100/8081 <- sg-mon (Phase 2 exporters) | 22 <- sg-ctrl, admin
#   sg-db    5432 <- sg-app, sg-ctrl | 9100/9187/8081 <- sg-mon (Phase 2)
#            22 <- sg-ctrl, admin
#   sg-mon   3000 <- admin | 9090/3100/3200 <- sg-ctrl (agent queries)
#            3100/4317-4318 <- sg-app (log + trace push) | 22 <- sg-ctrl, admin
#
# Ports with same-host-only traffic get NO rule: LiteLLM 4000 (agent->LiteLLM is
# localhost on ctrl-1) and Alertmanager 9093 (Prometheus->AM is localhost on mon-1).

# --- Security group definitions (empty; rules attached below) ---

resource "aws_security_group" "ctrl" {
  name        = "sentinel-sg-ctrl"
  description = "ctrl-1: agent API 8080, LiteLLM 4000, dashboard 3001"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "sentinel-sg-ctrl" }
}

resource "aws_security_group" "app" {
  name        = "sentinel-sg-app"
  description = "app-1/app-2: the 4 FastAPI services 8000-8003"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "sentinel-sg-app" }
}

resource "aws_security_group" "db" {
  name        = "sentinel-sg-db"
  description = "db-1: Postgres 5432 + pgvector"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "sentinel-sg-db" }
}

resource "aws_security_group" "mon" {
  name        = "sentinel-sg-mon"
  description = "mon-1: LGTM stack (Prometheus/Alertmanager/Grafana/Loki/Tempo)"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "sentinel-sg-mon" }
}

# --- Egress: allow-all outbound for every SG ---

resource "aws_vpc_security_group_egress_rule" "ctrl_all" {
  security_group_id = aws_security_group.ctrl.id
  description       = "all outbound (GHCR, Bedrock, apt)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  description       = "all outbound (GHCR, apt, inter-service)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "db_all" {
  security_group_id = aws_security_group.db.id
  description       = "all outbound (GHCR, apt)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "mon_all" {
  security_group_id = aws_security_group.mon.id
  description       = "all outbound (GHCR, apt, webhook to agent)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# --- sg-ctrl ingress ---

resource "aws_vpc_security_group_ingress_rule" "ctrl_agent_from_mon" {
  security_group_id            = aws_security_group.ctrl.id
  description                  = "Alertmanager webhook to agent API"
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
  referenced_security_group_id = aws_security_group.mon.id
}

resource "aws_vpc_security_group_ingress_rule" "ctrl_agent_from_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.ctrl.id
  description       = "you to agent API"
  ip_protocol       = "tcp"
  from_port         = 8080
  to_port           = 8080
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "ctrl_dashboard_from_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.ctrl.id
  description       = "you to dashboard UI"
  ip_protocol       = "tcp"
  from_port         = 3001
  to_port           = 3001
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "ctrl_ssh_from_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.ctrl.id
  description       = "you to SSH (ctrl-1 is the bastion)"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = each.value
}

# --- sg-app ingress ---

resource "aws_vpc_security_group_ingress_rule" "app_svc_from_app" {
  security_group_id            = aws_security_group.app.id
  description                  = "inter-service calls (gateway to orders to payments)"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8003
  referenced_security_group_id = aws_security_group.app.id
}

resource "aws_vpc_security_group_ingress_rule" "app_svc_from_ctrl" {
  security_group_id            = aws_security_group.app.id
  description                  = "agent to services (describe/health/remediate)"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8003
  referenced_security_group_id = aws_security_group.ctrl.id
}

resource "aws_vpc_security_group_ingress_rule" "app_svc_from_mon" {
  security_group_id            = aws_security_group.app.id
  description                  = "Prometheus scrape of service /metrics"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8003
  referenced_security_group_id = aws_security_group.mon.id
}

resource "aws_vpc_security_group_ingress_rule" "app_gateway_public" {
  security_group_id = aws_security_group.app.id
  description       = "public entry to api-gateway"
  ip_protocol       = "tcp"
  from_port         = 8000
  to_port           = 8000
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "app_node_exporter_from_mon" {
  security_group_id            = aws_security_group.app.id
  description                  = "node_exporter scrape (Phase 2)"
  ip_protocol                  = "tcp"
  from_port                    = 9100
  to_port                      = 9100
  referenced_security_group_id = aws_security_group.mon.id
}

resource "aws_vpc_security_group_ingress_rule" "app_cadvisor_from_mon" {
  security_group_id            = aws_security_group.app.id
  description                  = "cAdvisor scrape (Phase 2)"
  ip_protocol                  = "tcp"
  from_port                    = 8081
  to_port                      = 8081
  referenced_security_group_id = aws_security_group.mon.id
}

resource "aws_vpc_security_group_ingress_rule" "app_ssh_from_ctrl" {
  security_group_id            = aws_security_group.app.id
  description                  = "SSH from bastion (ctrl-1)"
  ip_protocol                  = "tcp"
  from_port                    = 22
  to_port                      = 22
  referenced_security_group_id = aws_security_group.ctrl.id
}

resource "aws_vpc_security_group_ingress_rule" "app_ssh_from_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.app.id
  description       = "SSH from you"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = each.value
}

# --- sg-db ingress ---

resource "aws_vpc_security_group_ingress_rule" "db_pg_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "orders-service to Postgres"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.app.id
}

resource "aws_vpc_security_group_ingress_rule" "db_pg_from_ctrl" {
  security_group_id            = aws_security_group.db.id
  description                  = "agent to Postgres (incidents/pgvector)"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.ctrl.id
}

resource "aws_vpc_security_group_ingress_rule" "db_node_exporter_from_mon" {
  security_group_id            = aws_security_group.db.id
  description                  = "node_exporter scrape (Phase 2)"
  ip_protocol                  = "tcp"
  from_port                    = 9100
  to_port                      = 9100
  referenced_security_group_id = aws_security_group.mon.id
}

resource "aws_vpc_security_group_ingress_rule" "db_pg_exporter_from_mon" {
  security_group_id            = aws_security_group.db.id
  description                  = "postgres_exporter scrape (Phase 2)"
  ip_protocol                  = "tcp"
  from_port                    = 9187
  to_port                      = 9187
  referenced_security_group_id = aws_security_group.mon.id
}

resource "aws_vpc_security_group_ingress_rule" "db_cadvisor_from_mon" {
  security_group_id            = aws_security_group.db.id
  description                  = "cAdvisor scrape (Phase 2)"
  ip_protocol                  = "tcp"
  from_port                    = 8081
  to_port                      = 8081
  referenced_security_group_id = aws_security_group.mon.id
}

resource "aws_vpc_security_group_ingress_rule" "db_ssh_from_ctrl" {
  security_group_id            = aws_security_group.db.id
  description                  = "SSH from bastion (ctrl-1)"
  ip_protocol                  = "tcp"
  from_port                    = 22
  to_port                      = 22
  referenced_security_group_id = aws_security_group.ctrl.id
}

resource "aws_vpc_security_group_ingress_rule" "db_ssh_from_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.db.id
  description       = "SSH from you"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = each.value
}

# --- sg-mon ingress ---

resource "aws_vpc_security_group_ingress_rule" "mon_grafana_from_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.mon.id
  description       = "you to Grafana UI"
  ip_protocol       = "tcp"
  from_port         = 3000
  to_port           = 3000
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "mon_prometheus_from_ctrl" {
  security_group_id            = aws_security_group.mon.id
  description                  = "agent PromQL queries"
  ip_protocol                  = "tcp"
  from_port                    = 9090
  to_port                      = 9090
  referenced_security_group_id = aws_security_group.ctrl.id
}

resource "aws_vpc_security_group_ingress_rule" "mon_loki_from_ctrl" {
  security_group_id            = aws_security_group.mon.id
  description                  = "agent LogQL queries"
  ip_protocol                  = "tcp"
  from_port                    = 3100
  to_port                      = 3100
  referenced_security_group_id = aws_security_group.ctrl.id
}

resource "aws_vpc_security_group_ingress_rule" "mon_tempo_from_ctrl" {
  security_group_id            = aws_security_group.mon.id
  description                  = "agent Tempo trace queries"
  ip_protocol                  = "tcp"
  from_port                    = 3200
  to_port                      = 3200
  referenced_security_group_id = aws_security_group.ctrl.id
}

resource "aws_vpc_security_group_ingress_rule" "mon_loki_from_app" {
  security_group_id            = aws_security_group.mon.id
  description                  = "promtail log push from app hosts"
  ip_protocol                  = "tcp"
  from_port                    = 3100
  to_port                      = 3100
  referenced_security_group_id = aws_security_group.app.id
}

resource "aws_vpc_security_group_ingress_rule" "mon_otlp_from_app" {
  security_group_id            = aws_security_group.mon.id
  description                  = "OTLP trace push from services (Tempo receiver)"
  ip_protocol                  = "tcp"
  from_port                    = 4317
  to_port                      = 4318
  referenced_security_group_id = aws_security_group.app.id
}

resource "aws_vpc_security_group_ingress_rule" "mon_ssh_from_ctrl" {
  security_group_id            = aws_security_group.mon.id
  description                  = "SSH from bastion (ctrl-1)"
  ip_protocol                  = "tcp"
  from_port                    = 22
  to_port                      = 22
  referenced_security_group_id = aws_security_group.ctrl.id
}

resource "aws_vpc_security_group_ingress_rule" "mon_ssh_from_admin" {
  for_each          = toset(var.admin_cidrs)
  security_group_id = aws_security_group.mon.id
  description       = "SSH from you"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = each.value
}
