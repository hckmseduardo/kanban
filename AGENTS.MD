We are focusing on create amazin tools.
the project should always use message queuen to order the tasks
all tasks should give feedback for the user during its process
we always display a feedback for the user when a task is completed
we don't touche anything on other stack docker running on the same server
we work a single configuration file and all necessary keys in an azure keyvault
we should keep an azure secret adding script as example using azure cli

always use the orchestrator to manipulate kanban-team and the apps

## Skills

Skills are documented in the `agent-skills/` folder. Each skill has its own `.md` file with usage instructions.

| Skill | Description | Documentation |
|-------|-------------|---------------|
| `/rebuild-workspace` | Rebuild and restart workspace containers via orchestrator | [rebuild-workspace.md](agent-skills/rebuild-workspace.md) |