const { defineConfig } = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const venv = path.join(__dirname, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const port = process.env.TEST_PORT || '8011';
const conda = path.join(os.homedir(), 'anaconda3', 'python.exe');
const python = process.env.TEST_PYTHON || (fs.existsSync(venv) ? venv : fs.existsSync(conda) ? conda : 'python');
module.exports = defineConfig({
  testDir: './e2e',
  outputDir: 'test-results/artifacts',
  timeout: 45000,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: process.env.PLAYWRIGHT_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined),
    viewport: { width: 1440, height: 1040 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: `"${python}" run.py`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 30000,
    env: { ...process.env, PORT: port, APP_DATA_DIR: path.join(__dirname, 'test-results', `db-${Date.now()}`), BEDROCK_ENABLED: 'false' }
  }
});
