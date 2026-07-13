output "hard_stop_budget" {
  description = "Name of the lifetime $100 hard-stop budget."
  value       = aws_budgets_budget.hard_stop.name
}
