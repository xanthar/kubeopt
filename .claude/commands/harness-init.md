Initialize claude-harness for this project.

First, check if claude-harness is already initialized by looking for `.claude-harness/config.json`.

If NOT initialized, help me set up claude-harness by:

1. **Detect the project stack** by running:
   ```bash
   claude-harness detect
   ```

2. **Ask me these questions** (use the detected values as defaults):
   - Project name? (default: current folder name)
   - What language? (default: detected)
   - What framework? (default: detected)
   - What port does the app run on? (default: 5000 for Python, 3000 for JS)
   - What test framework? (default: detected)
   - Enable E2E testing with Playwright? (default: no)
   - Enable subagent delegation? (default: no)

3. **Run the init command** with my answers:
   ```bash
   claude-harness init --non-interactive \
     --name "<project_name>" \
     --language "<language>" \
     --framework "<framework>" \
     --port <port> \
     --test-framework "<test_framework>" \
     [--e2e if enabled] \
     [--delegation if enabled]
   ```

4. **Show me the results** - what files were created and next steps.

If ALREADY initialized, tell me and show the current status with `claude-harness status`.
