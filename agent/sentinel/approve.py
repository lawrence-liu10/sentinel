"""CLI entrypoint: `python -m sentinel.approve <action_id> --approve|--reject --by <who>`."""

from sentinel.approvals import main

if __name__ == "__main__":
    main()
