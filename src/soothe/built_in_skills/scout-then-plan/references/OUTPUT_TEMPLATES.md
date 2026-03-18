# Output Templates

Structured templates for synthesis and plan outputs.

## Synthesis Template

Use this structure when synthesizing scout findings:

```markdown
## Synthesis: [Task Name]

### Findings Summary

[2-3 sentences summarizing what you discovered]

**Key files identified**:
- `path/to/file.py:line` - [What this file contains]
- `path/to/another.py:line` - [What this file contains]

### Patterns Discovered

**Pattern: [Pattern Name]**
- Description: [How the pattern works]
- Example: `file.py:line` shows [specific example]
- Usage: [When/where to apply this pattern]

**Pattern: [Another Pattern]**
- Description: [How it works]
- Example: [File reference]
- Usage: [When to apply]

### Constraints and Dependencies

**Must respect**:
- [Constraint 1 with file reference]
- [Constraint 2 with file reference]

**Depends on**:
- [Dependency 1]
- [Dependency 2]

### Gaps and Unknowns

**Remaining questions**:
- [Gap 1]: [Why it matters]
- [Gap 2]: [Impact if not resolved]

**Risks**:
- [Risk 1]: [Potential impact]
- [Risk 2]: [Potential impact]

### Context for Planning

[3-5 sentence summary providing the planner with essential context. Include:
- Current state of the system
- Key patterns to follow
- Critical constraints
- Known gaps]
```

### Example Synthesis

```markdown
## Synthesis: Add OAuth Integration

### Findings Summary

The codebase uses a middleware-based authentication system with JWT tokens. Found passport library in dependencies but not currently used. Auth middleware at `src/auth/middleware.py` validates tokens on each request.

**Key files identified**:
- `src/auth/middleware.py:15-45` - Token validation middleware
- `src/routes/auth.py:80-120` - Login/logout endpoints
- `config/settings.py:30` - JWT secret configuration

### Patterns Discovered

**Pattern: Middleware Registration**
- Description: Middleware is registered in `src/app.py` using `app.use(middleware)`
- Example: `src/app.py:23` shows logging middleware registration
- Usage: Add OAuth middleware after auth middleware in chain

**Pattern: Error Handling**
- Description: Errors use standardized `ApiError` class with status codes
- Example: `src/errors.py:12-30` defines error types
- Usage: OAuth errors should use `AuthenticationError` from this module

### Constraints and Dependencies

**Must respect**:
- Existing JWT auth must remain functional (backward compatibility)
- OAuth must integrate with existing user model (`src/models/user.py`)

**Depends on**:
- passport library (already in requirements.txt)
- Session management for OAuth state

### Gaps and Unknowns

**Remaining questions**:
- How to handle OAuth user provisioning: Should we auto-create users or require pre-registration?
- Token refresh strategy: How to handle OAuth token expiry?

**Risks**:
- Breaking existing auth: Middleware chain changes could affect JWT validation
- User identity conflicts: OAuth email might match existing user email

### Context for Planning

Current auth system uses JWT tokens validated by middleware. OAuth should follow the same middleware pattern, integrating with passport library. Must maintain backward compatibility with existing JWT auth. Key decision needed on user provisioning strategy (auto-create vs. pre-register). Follow error handling pattern from `src/errors.py`.
```

---

## Plan Template

Use this structure when creating plans (expected planner output):

```markdown
## Implementation Plan: [Task Name]

### Overview

[2-3 sentences describing the overall approach and goal]

### Steps

#### Step 1: [Step Title]

**Description**: [What to do]

**Rationale**: [Why this step matters]

**Dependencies**: [Which steps must complete first]

**Verification**: [How to confirm completion]

**Effort**: small/medium/large

**Files to modify**:
- `path/to/file.py` - [What to change]

#### Step 2: [Step Title]

[Same structure as Step 1]

#### Step N: [Step Title]

[Continue for all steps]

### Dependency Graph

```
Step 1 (no dependencies)
  ↓
Step 2 (depends on Step 1)
  ↓
Step 3 (depends on Step 2)
  ↓
Step 4 (depends on Steps 2 and 3)
```

### Testing Strategy

**Unit tests**:
- [What to test at unit level]

**Integration tests**:
- [What to test at integration level]

**Manual verification**:
- [How to manually verify the feature works]

### Rollback Plan

If issues arise:
1. [First rollback step]
2. [Second rollback step]

### Estimated Total Effort

[low/medium/high] - [Brief justification]
```

### Example Plan

```markdown
## Implementation Plan: Add OAuth Integration

### Overview

Add OAuth 2.0 authentication using passport library, integrating with existing middleware chain. Supports Google and GitHub providers. Maintains backward compatibility with existing JWT auth.

### Steps

#### Step 1: Install and Configure Passport

**Description**: Install passport library and configure OAuth providers (Google, GitHub) with client IDs and secrets.

**Rationale**: Required foundation for OAuth authentication.

**Dependencies**: None

**Verification**: Configuration loads without errors, provider credentials validated.

**Effort**: small

**Files to modify**:
- `requirements.txt` - Ensure passport is listed
- `config/settings.py` - Add OAuth configuration section
- `.env.example` - Document required OAuth environment variables

#### Step 2: Create OAuth Middleware

**Description**: Create OAuth middleware that handles OAuth callback, validates OAuth tokens, and establishes user sessions.

**Rationale**: Integrates OAuth with existing middleware chain following established patterns.

**Dependencies**: Step 1 (configuration)

**Verification**: Middleware can successfully authenticate OAuth users.

**Effort**: medium

**Files to modify**:
- `src/auth/oauth_middleware.py` (new) - OAuth middleware implementation
- `src/app.py:25` - Register OAuth middleware after auth middleware

#### Step 3: Add OAuth Routes

**Description**: Create routes for OAuth login initiation and callback handling.

**Rationale**: Provides endpoints for OAuth flow.

**Dependencies**: Step 2 (middleware)

**Verification**: Can initiate OAuth login and receive callback.

**Effort**: medium

**Files to modify**:
- `src/routes/auth.py` - Add `/auth/oauth/{provider}` and `/auth/oauth/callback/{provider}` routes

#### Step 4: Implement User Provisioning

**Description**: Handle user creation/retrieval for OAuth users. Auto-create users based on OAuth email.

**Rationale**: Resolves gap about user provisioning strategy.

**Dependencies**: Step 3 (routes)

**Verification**: New OAuth users are created, existing users are matched by email.

**Effort**: medium

**Files to modify**:
- `src/auth/user_service.py` - Add `find_or_create_by_oauth` method
- `src/models/user.py` - Add `oauth_provider` and `oauth_id` fields

#### Step 5: Add Tests

**Description**: Write unit and integration tests for OAuth flow.

**Rationale**: Ensures OAuth implementation works correctly and prevents regressions.

**Dependencies**: Steps 1-4 (implementation)

**Verification**: All tests pass.

**Effort**: medium

**Files to modify**:
- `tests/test_oauth_middleware.py` (new) - OAuth middleware tests
- `tests/test_auth_routes.py` - Add OAuth route tests

### Dependency Graph

```
Step 1 (configuration)
  ↓
Step 2 (middleware)
  ↓
Step 3 (routes)
  ↓
Step 4 (user provisioning)
  ↓
Step 5 (tests)
```

### Testing Strategy

**Unit tests**:
- OAuth middleware token validation
- User service `find_or_create_by_oauth` logic
- Configuration loading

**Integration tests**:
- Full OAuth flow with mock provider
- Backward compatibility with JWT auth
- User creation and matching

**Manual verification**:
- Login with Google OAuth
- Login with GitHub OAuth
- Verify existing JWT auth still works
- Check user provisioning creates correct users

### Rollback Plan

If issues arise:
1. Remove OAuth middleware from `src/app.py`
2. Remove OAuth routes from `src/routes/auth.py`
3. Revert database schema changes
4. System returns to JWT-only auth

### Estimated Total Effort

medium - Requires new middleware, routes, user service logic, and comprehensive testing, but follows existing patterns.
```

---

## Reflection Template

Use this structure when reflecting on your workflow:

```markdown
## Reflection: [Task Name]

### What Went Well

- [Aspect that worked effectively]
- [Another positive aspect]

### Challenges Encountered

- [Challenge 1]: [How you addressed it]
- [Challenge 2]: [How you addressed it]

### Gaps Discovered During Planning

- [Gap identified during planning that scouts missed]
- [Why the scouts missed it]

### Lessons Learned

- [Key learning 1]
- [Key learning 2]

### Recommendations for Future

- [Recommendation for similar tasks]
- [Tool or technique to try next time]
```

---

## Quick Reference

### Synthesis Checklist
- [ ] Findings summarized with file citations
- [ ] Patterns identified with examples
- [ ] Constraints documented
- [ ] Gaps acknowledged
- [ ] Context provides clear direction for planner

### Plan Checklist
- [ ] Steps are sequential and clear
- [ ] Dependencies explicitly stated
- [ ] Each step has verification criteria
- [ ] Files to modify are listed
- [ ] Effort estimates provided
- [ ] Testing strategy included
- [ ] Rollback plan exists
