import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AliceStatus } from '../types'

// Os dados vivem na VM (Lightsail); o alias alice-vm está em ~/.ssh/config
const STATUS_COMMAND = [
  'C:/Windows/System32/OpenSSH/ssh.exe', '-T', '-o', 'BatchMode=yes', 'alice-vm',
  'sudo', '-n', '-u', 'alice', '/opt/alice/bin/alice-status',
]
const MEMORIES_SEPARATOR = '<<<ALICE-MEMORIAS>>>'

// A mesma cor de destaque da CLI (src/cli.py)
const ACCENT = 'magenta'

const WEEKDAYS = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado']
const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
const SPINNER_WORDS = ['Organizando', 'Priorizando', 'Lembrando', 'Integrando', 'Cobrando', 'Pesando custos', 'Protegendo a margem']
const ITEM_RE = /^\s*[-*] \[( )\]\s*(.+?)\s*$/

const status = atom({ plugin: 'alice-skin', key: 'status' } as const, null)

// tarefas.md e memorias_vivas.md numa só conexão; null se a VM não responder
async function fetchFromVm($: EngineInterface): Promise<{ tasks: string; memories: string } | null> {
  try {
    const { exitCode, stdout } = await $.process.run(STATUS_COMMAND, { timeoutMs: 15000 })
    if (exitCode !== 0 || !stdout.includes(MEMORIES_SEPARATOR)) return null
    const [tasks = '', memories = ''] = stdout.split(MEMORIES_SEPARATOR)
    return { tasks, memories }
  } catch {
    return null
  }
}

function countInbox(markdown: string): number {
  let inside = false
  let count = 0
  for (const line of markdown.split(/\r?\n/)) {
    if (line.startsWith('## ')) {
      inside = line.toUpperCase().includes('INBOX')
      continue
    }
    if (inside && ITEM_RE.test(line)) count += 1
  }
  return count
}

function today(): string {
  const now = new Date()
  return `${WEEKDAYS[now.getDay()]}, ${now.getDate()} ${MONTHS[now.getMonth()]}`
}

async function refresh($: EngineInterface): Promise<void> {
  const data = await fetchFromVm($)
  // Sem conexão, mantém o último cabeçalho em vez de mostrar zeros
  if (data === null) return
  const { tasks, memories } = data
  const next: AliceStatus = {
    inbox: countInbox(tasks),
    memories: memories.split(/\r?\n/).filter(line => line.startsWith('- ')).length,
    date: today(),
  }
  await update($, status, () => next)
}

// Escolha estável por turno: o engine sorteia uma palavra, e a mesma palavra
// sempre vira a mesma tradução, então o spinner não pisca entre redesenhos.
function pick<T>(list: readonly T[], seed: string): T {
  let hash = 0
  for (const char of seed) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return list[hash % list.length] as T
}

function formatDuration(ms: number): string {
  const seconds = Math.round(ms / 1000)
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function truncate(text: unknown, size = 70): string {
  const value = typeof text === 'string' ? text : ''
  return value.length > size ? `${value.slice(0, size - 1)}…` : value
}

// Uma linha legível para cada ferramenta do MCP da ALICE
function describeTool(tool: string, input: Record<string, unknown>): string {
  switch (tool) {
    case 'mcp__alice__add_to_inbox':
      return `INBOX + ${truncate(input.item_text)}`
    case 'mcp__alice__add_task':
      return `${truncate(input.section, 20) || 'INBOX'} + ${truncate(input.text)}`
    case 'mcp__alice__complete_task':
      return `✓ ${truncate(input.item)}`
    case 'mcp__alice__move_task':
      return `${truncate(input.item, 50)} → ${truncate(input.section, 20)}`
    case 'mcp__alice__remove_task':
      return `− ${truncate(input.item)}`
    case 'mcp__alice__add_memory':
      return `memória: ${truncate(input.fact)}`
    case 'mcp__alice__update_tasks':
      return `tarefas.md atualizado (${truncate(input.reason, 50) || 'sem motivo'})`
    case 'mcp__alice__get_tasks':
      return 'consultou as tarefas'
    case 'mcp__alice__get_profile':
      return 'consultou o perfil'
    case 'mcp__alice__get_memories':
      return 'consultou as memórias'
    default:
      return tool.replace('mcp__alice__', '')
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await refresh($)
    return next(e)
  })

  // Só observa: nunca bloqueia uma chamada, nem se a releitura falhar
  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    if (e.tool.startsWith('mcp__alice__')) await refresh($)
    return result
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    await refresh($)
    return next(e)
  })

  // Cabeçalho fixo acima do prompt
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, status)
    if (e.props.hasSurvey || current === null) return next(e)

    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box>
        <Text color={ACCENT} bold>● ALICE</Text>
        <Text dimColor>
          {`  ${current.date} · inbox ${current.inbox} · memórias ${current.memories}`}
        </Text>
      </Box>
    )
  })

  // Nome acima de cada resposta
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    if (!e.props.isFirstOfReply || e.props.isSummary) return next(e)

    const drawn = await next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        <Text color={ACCENT} bold>ALICE</Text>
        {drawn}
      </Box>
    )
  })

  // Spinner em português, no vocabulário dela
  on('ui.render', { component: 'Spinner' }, ($, e, next) =>
    next({ ...e, props: { ...e.props, word: pick(SPINNER_WORDS, e.props.word) } }),
  )

  // Linha de fim de turno
  on('ui.render', { component: 'TurnDuration' }, ($, e, next) => {
    if (e.props.isExpanded || e.props.waitingFor) return next(e)

    const { Text } = $.ui.resolve(e)
    return <Text dimColor>{`✻ resolvido em ${formatDuration(e.props.durationMs)}`}</Text>
  })

  // Chamadas ao MCP da ALICE como linhas curtas, em vez de "alice - add_to_inbox (MCP)(...)"
  on('ui.render', { component: 'ToolUse' }, ($, e, next) => {
    const { tool, input, isRunning, isErrored, isExpanded } = e.props
    if (!tool.startsWith('mcp__alice__') || isExpanded) return next(e)

    const { Text } = $.ui.resolve(e)
    const label = describeTool(tool, (input ?? {}) as Record<string, unknown>)
    if (isErrored) return <Text color="red">{`✗ ${label}`}</Text>
    return (
      <Text>
        <Text color={isRunning ? undefined : ACCENT} dimColor={isRunning}>◆ </Text>
        <Text dimColor={isRunning}>{label}</Text>
      </Text>
    )
  })
}
