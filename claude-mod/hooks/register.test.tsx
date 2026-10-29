import { expect, test } from 'claude-code/testing'

const TASKS = '## 📥 INBOX (A Processar)\n- [ ] comprar café\n- [ ] ligar para o dentista\n- [x] feito\n\n## 🎓 Estudos\n- [ ] estudar\n'
const MEMORIES = '- [SAÚDE] treina às terças\n'

const BAND = {
  plugin: 'alice-skin',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 10 },
    view: {},
  },
} as const

test('o cabeçalho conta só os itens abertos do INBOX, lidos da VM', async ($, on) => {
  on('process.run', () => ({
    value: {
      exitCode: 0,
      stdout: `${TASKS}<<<ALICE-MEMORIAS>>>\n${MEMORIES}`,
      stderr: '',
      isStdoutTruncated: false,
      isStderrTruncated: false,
    },
  }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
    const row = await ui.find({ type: 'Text', text: /inbox/ })
    expect(row?.text).toContain('inbox 2 · memórias 1')
    await ui.unmount()
  }
})

test('uma chamada ao MCP da ALICE vira uma linha curta', async ($, on) => {
  const ui = await $.ui.mount({
    plugin: 'alice-skin',
    surface: 'terminal',
    component: 'ToolUse',
    props: {
      tool_use_id: 't1',
      tool: 'mcp__alice__add_to_inbox',
      input: { item_text: 'comprar café' },
      isRunning: false,
      isErrored: false,
      isInterrupted: false,
    },
  })
  expect((await ui.find({ type: 'Text', text: /INBOX/ }))?.text).toContain('INBOX + comprar café')
  await ui.unmount()
})

test('o fim do turno aparece em português', async ($, on) => {
  const ui = await $.ui.mount({
    plugin: 'alice-skin',
    surface: 'terminal',
    component: 'TurnDuration',
    props: { word: 'Baked', durationMs: 64000 },
  })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('✻ resolvido em 1m 4s')
  await ui.unmount()
})
