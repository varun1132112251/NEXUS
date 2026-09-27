# NEXUS Core Architecture

## 1. Purpose

The NEXUS Core is the persistent state and execution foundation of the NEXUS system.

NEXUS is designed as a personal operating layer that maintains structured knowledge of a user's long-running goals, tasks, constraints, context, actions, and outcomes.

The core must support:

* persistent objectives
* task decomposition
* task dependencies
* controlled state transitions
* immutable task history
* future autonomous planning
* future agent execution
* recovery and replanning
* auditability
* explainability

The core is intentionally independent of any particular LLM or agent framework.

---

## 2. Core Domain Model

The first domain model consists of:

```text
User
  |
  └── Goal
        |
        └── Task
              |
              ├── TaskDependency
              |
              └── TaskEvent
```

### User

An authenticated NEXUS user.

Users already exist in the authentication subsystem.

A Goal belongs to exactly one User.

---

## 3. Goal

A Goal represents a persistent long-running objective.

Examples:

* Get an AI/ML internship
* Build NEXUS v1
* Prepare for GATE
* Complete a major project

### Goal attributes

```text
id
user_id
title
description
status
priority
constraints
created_at
updated_at
```

### Goal responsibilities

A Goal represents the desired outcome rather than a single action.

A Goal can contain multiple Tasks.

---

## 4. Task

A Task represents a concrete unit of work that contributes toward a Goal.

### Task attributes

```text
id
goal_id
title
description
status
priority
due_at
created_at
updated_at
```

A Task must belong to exactly one Goal.

Tasks may depend on other Tasks.

---

## 5. Task Dependency

A TaskDependency represents an ordering or prerequisite relationship.

Example:

```text
Research target companies
        |
        v
Prepare resume
        |
        v
Submit applications
```

The dependency relation is:

```text
task_id
depends_on_task_id
```

A task cannot become executable while a required dependency remains incomplete.

The design must prevent a task from depending on itself.

Future versions must also prevent dependency cycles.

---

## 6. Task State Machine

Tasks use explicit states.

```text
CREATED
   |
   v
PLANNED
   |
   v
READY
   |
   v
RUNNING
   |
   +------> BLOCKED
   |           |
   |           v
   |         READY
   |
   +------> VERIFYING
   |           |
   |           +----> COMPLETED
   |           |
   |           +----> FAILED
   |
   +------> FAILED

BLOCKED
   |
   +----> READY
   |
   +----> CANCELLED

CREATED
   |
   +----> CANCELLED

PLANNED
   |
   +----> CANCELLED

READY
   |
   +----> CANCELLED
```

### Terminal states

The following states are terminal:

```text
COMPLETED
CANCELLED
```

A terminal task must not transition into another state.

---

## 7. State Transition Rules

Valid transitions:

```text
CREATED     -> PLANNED
CREATED     -> CANCELLED

PLANNED     -> READY
PLANNED     -> CANCELLED

READY       -> RUNNING
READY       -> CANCELLED

RUNNING     -> BLOCKED
RUNNING     -> VERIFYING
RUNNING     -> FAILED

BLOCKED     -> READY
BLOCKED     -> CANCELLED

VERIFYING   -> COMPLETED
VERIFYING   -> FAILED
```

Examples of invalid transitions:

```text
CREATED     -> COMPLETED
CREATED     -> RUNNING
COMPLETED   -> RUNNING
CANCELLED   -> READY
FAILED      -> RUNNING
```

State transitions must occur through domain logic rather than arbitrary direct status mutation.

---

## 8. Task Events

Every significant task transition produces an immutable TaskEvent.

A TaskEvent represents something that happened to a Task.

Examples:

```text
TASK_CREATED
TASK_PLANNED
TASK_READY
TASK_STARTED
TASK_BLOCKED
TASK_RESUMED
TASK_VERIFICATION_STARTED
TASK_COMPLETED
TASK_FAILED
TASK_CANCELLED
```

### Event attributes

```text
id
task_id
event_type
from_state
to_state
metadata
created_at
```

The event history must be append-only.

Task events provide:

* auditability
* debugging
* observability
* future replay
* failure analysis
* explainability
* future agent reasoning context

---

## 9. Domain Invariants

The system must preserve these invariants.

### Ownership

```text
User -> Goal -> Task
```

A task must never belong to a Goal owned by another User.

### State integrity

Every state change must correspond to a valid transition.

### Event integrity

A successful state transition must create the corresponding TaskEvent.

### Dependency integrity

A task cannot execute while required dependencies remain incomplete.

### Terminal integrity

Completed and cancelled tasks cannot be modified through normal state transitions.

---

## 10. Why Events Are First-Class

The current state answers:

```text
What is happening now?
```

The event history answers:

```text
How did we get here?
```

NEXUS requires both.

Future subsystems can use TaskEvent history for:

* agent decision context
* debugging
* recovery
* analytics
* user explanations
* realtime event streaming
* evaluation
* replay

---

## 11. Future Planning Integration

The Planner will eventually consume:

```text
Goal
Task graph
Task dependencies
Task state
Task events
Constraints
User context
```

and produce:

```text
Task decomposition
Execution order
Required capabilities
Expected outcomes
```

The Planner must not directly mutate database state.

Instead:

```text
Planner
   |
   v
Proposed transition/action
   |
   v
Domain layer
   |
   v
Validation
   |
   v
Persistence
   |
   v
TaskEvent
```

This keeps planning separate from state mutation.

---

## 12. Future Agent Integration

Agents will eventually operate through the same core.

Conceptually:

```text
Goal
  |
  v
Planner
  |
  v
Task
  |
  v
Agent
  |
  v
Action
  |
  v
Tool
  |
  v
Result
  |
  v
Verification
  |
  v
TaskEvent
  |
  v
Updated State
  |
  v
Replanning
```

The NEXUS Core therefore must remain independent of the LLM provider and agent framework.

---

## 13. Failure and Recovery

A task can fail because of:

* tool failure
* external service failure
* missing information
* unmet dependency
* validation failure
* execution timeout
* agent error

Failure must be represented explicitly.

Future recovery logic will inspect:

```text
current state
event history
error metadata
dependencies
available tools
constraints
```

and determine whether the task can be retried, modified, blocked, or abandoned.

---

## 14. Design Principle

NEXUS is not intended to be a simple CRUD task manager.

The core exists to support a continuous loop:

```text
Goal
  ↓
Plan
  ↓
Execute
  ↓
Observe
  ↓
Verify
  ↓
Update State
  ↓
Remember
  ↓
Replan
  ↓
Execute Again
```

The architecture must preserve enough structured information for that loop to operate reliably over long periods.

---

## 15. Phase 4A Scope

Phase 4A implements only the foundational persistence and domain layer:

```text
Goal
Task
TaskDependency
TaskEvent
Task state machine
State transition validation
Database migration
Tests
```

The following are intentionally deferred:

```text
LLM integration
Agent orchestration
Tool execution
Voice
Realtime streaming
Frontend
Autonomous planning
Long-term memory
External integrations
```

These systems will build on the NEXUS Core rather than define it.

---

## 16. Success Criteria

Phase 4A is complete when:

1. Goals can be persisted for authenticated users.
2. Tasks can be persisted under Goals.
3. Task dependencies can be represented safely.
4. Invalid dependency relationships are rejected.
5. Task state transitions are validated.
6. Every valid state transition creates an immutable event.
7. Invalid transitions are rejected.
8. Terminal tasks cannot transition again.
9. Database migrations can be applied and reversed.
10. Automated tests cover domain invariants and persistence behavior.
11. The design does not depend on an LLM provider.
