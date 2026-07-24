"""list_recent_deploys — reads the deploy log the deploy playbook writes (§2)."""

from sentinel import schemas


def list_recent(store, p: schemas.ListRecentDeploysParams) -> dict:
    return {"deploys": store.list_deploys(p.service, p.limit)}
