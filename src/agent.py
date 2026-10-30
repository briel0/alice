import warnings
warnings.filterwarnings("ignore")

import json
from datetime import datetime
from pathlib import Path
from google import genai
from google.genai import types
import anthropic

from src.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    BASE_DIR,
    DATA_DIR,
    USER_NAME
)
from src import planner, storage, treinos
from src.treinos import Serie
from src.storage import read_tasks_markdown
from src.history import append_message, get_recent_history
from src.guardrails import check_guardrails, record_token_usage

MAX_TOOL_ROUNDS = 5

PROFILE_FILE = DATA_DIR / "perfil.md"
MEMORIES_FILE = DATA_DIR / "memorias_vivas.md"
GUIDELINES_FILE = DATA_DIR / "diretrizes.md"

def load_user_profile() -> str:
    if PROFILE_FILE.exists():
        return PROFILE_FILE.read_text(encoding="utf-8")
    return ""

def load_memories() -> str:
    if MEMORIES_FILE.exists():
        return MEMORIES_FILE.read_text(encoding="utf-8")
    return ""

def load_personal_guidelines() -> str:
    if GUIDELINES_FILE.exists():
        return GUIDELINES_FILE.read_text(encoding="utf-8")
    return ""

# Comportamento genérico. O que é pessoal (missão, riscos, frentes de vida) fica em data/diretrizes.md.
BASE_INSTRUCTIONS = """
Você é a “ALICE” (ALICE Lembra, Integra, Cobra e Executa), assistente pessoal do usuário.

SUA MISSÃO:
Ajudar o usuário a decidir o que merece ser feito, preservar margem e manter consistência. Mais produtividade não é automaticamente melhor.

DIRETRIZES DE COMPORTAMENTO:
1. Tom: direto, maduro, técnico quando o assunto pedir, sem bajulação, sem elogios vazios e sem paternalismo.
2. Fale a verdade: se o usuário estiver se iludindo com o tempo disponível, assumindo compromissos demais ou fazendo uma ideia ruim parecer inteligente, diga isso.
3. Quando uma nova ideia ou demanda surgir:
   - Avalie: "Isso precisa virar projeto agora? O que teria que sair para isso entrar?"
   - Se for algo rápido para anotar sem pensar, jogue no INBOX usando `add_task`.
   - Se não for foco imediato, direcione para 'ALGUM DIA / TALVEZ'.
4. Memórias vivas: se o usuário mencionar um fato novo sobre a vida dele (viagens, pessoas, hábitos, preferências), use `add_memory` para salvar silenciosamente.
5. Formato para decisões importantes: SITUAÇÃO, OPÇÕES, CUSTOS (especialmente custo de oportunidade), RECOMENDAÇÃO, PRÓXIMA AÇÃO.
6. Se o usuário parecer sobrecarregado, simplifique em: AGORA, DEPOIS, NÃO AGORA.
7. Pergunta objetiva ("qual a minha lista de compras?", "o que tenho para hoje?") recebe resposta direta: só a informação, sem dizer de onde ela veio, sem introdução e sem comentário, a menos que o usuário peça ou que haja algo realmente importante a avisar.
8. As diretrizes pessoais e o perfil abaixo, quando existirem, têm prioridade sobre estas instruções gerais.
"""

TASK_RULES = """
REGRAS PARA MEXER NO tarefas.md:
- Você NUNCA reescreve o arquivo. Só existem edições de uma linha:
  - `add_task(text, section)`: cria um item. Sem seção clara, use "INBOX".
  - `complete_task(item)`: marca um item aberto como concluído.
  - `move_task(item, section)`: move um item para outra seção.
  - `remove_task(item)`: apaga um item (só quando o usuário pedir para apagar ou for duplicado).
- `item` é o texto do item como aparece no arquivo (pode ser um trecho que o identifique sem ambiguidade).
- `section` é parte do título da seção, por exemplo "INBOX", "Estudos", "AGUARDANDO", "ALGUM DIA".
- Para várias mudanças, chame uma ferramenta por mudança.
- LISTA DE COMPRAS: o que o usuário precisa comprar vai para a seção "COMPRAS", um item por coisa: "preciso comprar arroz e alguma mistura barata" são duas chamadas de `add_task` ("Arroz" e "Alguma mistura barata"). Mantenha as palavras do usuário (item vago continua vago; não escolha marca nem produto por ele) e inclua a quantidade quando ele disser. Quando ele disser que comprou, use `remove_task`: a lista guarda só o que falta comprar.
- Se a ferramenta responder que não encontrou ou que há mais de um item, não invente: pergunte ao usuário.
- Só diga que algo foi feito depois que a ferramenta confirmar.
"""

# Só entra no prompt quando o Planner está configurado (PLANNER_API_URL)
PLANNER_RULES = """
PLANNER (PROJETOS):
- O usuário também usa o Planner, um app de quadros para projetos e visão de longo prazo.
- tarefas.md é o tático: ações do dia, anotações rápidas, rotinas. Projetos, ideias grandes e coisas de vários passos vão para o Planner com `create_card(title, category, description)`.
- Por aqui você só CRIA cartões no Planner. Organizar, mover, editar e apagar é com o usuário, no PC.
- Se o usuário mandar um projeto de vários passos, crie um cartão para o projeto no Planner e, se houver, anote no tarefas.md só a próxima ação concreta.
- Sem categoria clara, deixe `category` vazio: o cartão vai para a categoria de entrada do Planner.
"""

# Só entra no prompt quando a API de treinos está configurada (TREINOS_API_URL)
TREINOS_RULES = """
TREINOS:
- Registre só os exercícios da mensagem atual: os das mensagens anteriores do histórico já foram registrados (ou recusados) e registrar de novo duplica.
- Registre cada exercício feito com `log_exercise(exercise, sets, day)`, uma chamada por exercício, todas na mesma resposta quando vierem juntos. Os exercícios entram no treino do dia (criado na primeira chamada).
- `exercise` é o nome ou apelido como o usuário falou ("supino", "paralela"); a API acha no catálogo.
- `sets` tem um item por série: "4x10 com 60" são 4 séries de reps=10, load_kg=60; "10, 8, 6 com 20" são 3 séries. Preencha só o que o exercício usa: musculação reps e load_kg; peso corporal reps (load_kg só com carga extra, assistance_kg com máquina ou elástico); por tempo duration_sec; cardio distance_m e duration_sec. Unilateral: side "left" ou "right".
- Sem carga num exercício com pesos, não invente: pergunte.
- `day` vazio é hoje; para outro dia, AAAA-MM-DD.
- Peso corporal: `log_body_weight(weight_kg, day)`.
- Se a ferramenta disser que não achou o exercício ou que recusou as séries, pergunte ao usuário em vez de chutar.
- Você não cria exercícios no catálogo. Se um exercício não existir, sugira o nome mais parecido da lista que a ferramenta devolveu ou combine com o usuário deixar de fora; nunca ofereça criar.
- Para corrigir um registro errado, use `remove_exercise(exercise, day)` (tira a ocorrência mais recente do exercício no treino do dia) e, se for o caso, registre de novo com os valores certos. Só tire quando o usuário pedir ou confirmar a correção.
- Depois de registrar, mostre em poucas linhas o que a ferramenta confirmou (nome do exercício no catálogo e séries), para o usuário conferir.
"""

# Definição das ferramentas (as docstrings viram a descrição para o Gemini)
def add_task(text: str, section: str = "INBOX") -> str:
    """Adiciona um item aberto ("- [ ] text") ao fim de uma seção do tarefas.md. section é parte do título, ex.: INBOX, Estudos, AGUARDANDO."""
    return storage.add_task(text, section)

def complete_task(item: str) -> str:
    """Marca como concluído o item aberto cujo texto contém `item`."""
    return storage.complete_task(item)

def move_task(item: str, section: str) -> str:
    """Move o item cujo texto contém `item` para o fim da seção indicada."""
    return storage.move_task(item, section)

def remove_task(item: str) -> str:
    """Apaga o item cujo texto contém `item`. Use só quando o usuário pedir para apagar ou para itens duplicados."""
    return storage.remove_task(item)

def get_current_tasks() -> str:
    """Lê e retorna o conteúdo atual do tarefas.md."""
    return read_tasks_markdown()

def add_memory(fact: str, category: str = "geral") -> str:
    """Salva uma memória viva: fato pessoal, preferência ou mudança de rotina sobre o usuário."""
    MEMORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORIES_FILE, "a", encoding="utf-8") as f:
        f.write(f"- [{category.upper()}] {fact}\n")
    return f"Memória registrada: [{category}] {fact}"

def create_card(title: str, category: str = "", description: str = "") -> str:
    """Cria um cartão no Planner (app de quadros de projetos). Para projetos, ideias grandes e coisas de vários passos. category é parte do nome de uma categoria do Planner; vazio vai para a categoria de entrada. description é opcional. Só cria: não edita, não move, não apaga."""
    return planner.create_card(title, category, description)

def log_exercise(exercise: str, sets: list[Serie], day: str = "") -> str:
    """Registra um exercício feito, com as séries, no treino do dia (cria o treino se ainda não houver). exercise é o nome ou apelido do exercício. sets tem um item por série, com só as medidas que o exercício usa. day é AAAA-MM-DD; vazio é hoje."""
    return treinos.log_exercise(exercise, sets, day)

def remove_exercise(exercise: str, day: str = "") -> str:
    """Tira do treino do dia a ocorrência mais recente de um exercício, com as séries. Para corrigir registros errados. day é AAAA-MM-DD; vazio é hoje."""
    return treinos.remove_exercise(exercise, day)

def log_body_weight(weight_kg: float, day: str = "") -> str:
    """Registra o peso corporal do usuário no dia (substitui se já houver). day é AAAA-MM-DD; vazio é hoje."""
    return treinos.log_body_weight(weight_kg, day)

def available_tools() -> list:
    """Ferramentas oferecidas ao Gemini; as do Planner e do Treinos só quando configurados."""
    tools = [add_task, complete_task, move_task, remove_task, get_current_tasks, add_memory]
    if planner.is_enabled():
        tools.append(create_card)
    if treinos.is_enabled():
        tools += [log_exercise, remove_exercise, log_body_weight]
    return tools

ITEM_PROPERTY = {"type": "string", "description": "Texto (ou trecho único) do item como aparece no arquivo"}
SECTION_PROPERTY = {"type": "string", "description": "Parte do título da seção, ex.: INBOX, Estudos, AGUARDANDO"}

CLAUDE_TOOLS = [
    {
        "name": "add_task",
        "description": add_task.__doc__,
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texto do novo item"},
                "section": SECTION_PROPERTY
            },
            "required": ["text"]
        }
    },
    {
        "name": "complete_task",
        "description": complete_task.__doc__,
        "input_schema": {"type": "object", "properties": {"item": ITEM_PROPERTY}, "required": ["item"]}
    },
    {
        "name": "move_task",
        "description": move_task.__doc__,
        "input_schema": {
            "type": "object",
            "properties": {"item": ITEM_PROPERTY, "section": SECTION_PROPERTY},
            "required": ["item", "section"]
        }
    },
    {
        "name": "remove_task",
        "description": remove_task.__doc__,
        "input_schema": {"type": "object", "properties": {"item": ITEM_PROPERTY}, "required": ["item"]}
    },
    {
        "name": "add_memory",
        "description": "Salva uma memória viva, fato pessoal, preferência ou mudança de rotina sobre o usuário.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "O fato aprendido"},
                "category": {"type": "string", "description": "Categoria (ex: saúde, rotina, pessoas)", "default": "geral"}
            },
            "required": ["fact"]
        }
    },
    {
        "name": "get_current_tasks",
        "description": "Lê e retorna o conteúdo atual do tarefas.md.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]

def execute_tool(name: str, args: dict) -> str:
    if name == "add_task":
        return add_task(args.get("text", ""), args.get("section", "INBOX"))
    elif name == "complete_task":
        return complete_task(args.get("item", ""))
    elif name == "move_task":
        return move_task(args.get("item", ""), args.get("section", ""))
    elif name == "remove_task":
        return remove_task(args.get("item", ""))
    elif name == "add_memory":
        return add_memory(args.get("fact", ""), args.get("category", "geral"))
    elif name == "get_current_tasks":
        return get_current_tasks()
    elif name == "create_card" and planner.is_enabled():
        return create_card(args.get("title", ""), args.get("category", ""), args.get("description", ""))
    elif name == "log_exercise" and treinos.is_enabled():
        return log_exercise(args.get("exercise", ""), args.get("sets") or [], args.get("day", ""))
    elif name == "remove_exercise" and treinos.is_enabled():
        return remove_exercise(args.get("exercise", ""), args.get("day", ""))
    elif name == "log_body_weight" and treinos.is_enabled():
        return log_body_weight(args.get("weight_kg", 0), args.get("day", ""))
    return f"Ferramenta desconhecida: {name}"

def _process_with_claude(user_text: str, system_prompt: str, history: list[dict]) -> str:
    """Processa a mensagem usando a API da Anthropic (Claude 3.5 Haiku/Sonnet)."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    messages = []
    for item in history:
        role = "user" if item["role"] == "user" else "assistant"
        messages.append({"role": role, "content": item["content"]})
        
    messages.append({"role": "user", "content": user_text})
    
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=messages,
        tools=CLAUDE_TOOLS,
        temperature=0.3
    )
    
    # Registra o uso de tokens na trava de segurança
    record_token_usage(response.usage.input_tokens, response.usage.output_tokens)
    
    # Se chamou ferramentas
    if response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                res = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": res
                })
                
        # Continua a conversa enviando os resultados das tools
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
        
        final_response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=CLAUDE_TOOLS,
            temperature=0.3
        )
        record_token_usage(final_response.usage.input_tokens, final_response.usage.output_tokens)
        
        text_blocks = [b.text for b in final_response.content if hasattr(b, "text")]
        return "".join(text_blocks) or "Feito. Tarefas e estado atualizados."
        
    text_blocks = [b.text for b in response.content if hasattr(b, "text")]
    return "".join(text_blocks) or "Entendido."

def _process_with_gemini(user_text: str | None, audio_bytes: bytes | None, mime_type: str, system_prompt: str, history: list[dict]) -> str:
    """Processa mensagem ou áudio usando a API do Gemini."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    contents: list[types.Content] = []
    for item in history:
        role = "user" if item["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=item["content"])]))
        
    current_parts: list[types.Part] = []
    if audio_bytes:
        current_parts.append(types.Part.from_bytes(data=audio_bytes, mime_type=mime_type))
        prompt_text = "Áudio do usuário via Telegram. Ouça atentamente, processe e execute ações se necessário."
        if user_text:
            prompt_text += f"\nTexto complementar: {user_text}"
        current_parts.append(types.Part.from_text(text=prompt_text))
    else:
        current_parts.append(types.Part.from_text(text=user_text or ""))
        
    contents.append(types.Content(role="user", parts=current_parts))

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=available_tools(),
        temperature=0.3,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    # Algumas rodadas de ferramentas permitem encadear (ex.: concluir um item e criar outro)
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )
        if not response.function_calls:
            return response.text or "Entendido."

        tool_results = []
        for call in response.function_calls:
            res = execute_tool(call.name, call.args or {})
            tool_results.append(types.Part.from_function_response(name=call.name, response={"result": res}))
        contents.append(response.candidates[0].content)
        contents.append(types.Content(role="user", parts=tool_results))

    return response.text or "Feito. Tarefas e estado atualizados."

def process_user_message(
    user_text: str | None = None,
    audio_bytes: bytes | None = None,
    mime_type: str = "audio/ogg",
    user_id: int | None = None
) -> str:
    """Ponto de entrada único com Circuit Breaker de custos e fallback inteligente."""
    
    # 1. VERIFICA O DISJUNTOR DE SEGURANÇA (Circuit Breaker)
    allowed, block_reason = check_guardrails()
    if not allowed:
        return block_reason

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
    current_tasks = read_tasks_markdown()
    user_profile = load_user_profile()
    memories = load_memories()
    guidelines = load_personal_guidelines()
    user_line = f"O nome do usuário é {USER_NAME}.\n" if USER_NAME else ""
    planner_rules = PLANNER_RULES if planner.is_enabled() else ""
    treinos_rules = TREINOS_RULES if treinos.is_enabled() else ""

    system_prompt = (
        f"{BASE_INSTRUCTIONS}\n{user_line}{TASK_RULES}{planner_rules}{treinos_rules}\n"
        f"[DIRETRIZES PESSOAIS]\n{guidelines}\n\n"
        f"[PERFIL E PRINCÍPIOS DO USUÁRIO]\n{user_profile}\n\n"
        f"[MEMÓRIAS VIVAS APRENDIDAS]\n{memories}\n\n"
        f"[ESTADO ATUAL OPERACIONAL]\n"
        f"Data/Hora: {current_time}\n"
        f"Arquivo tarefas.md:\n{current_tasks}\n"
    )
    
    history = get_recent_history(limit=16)
    recorded_user_message = user_text or "[Áudio de voz]"
    
    # 2. SELETOR DE MODELO: Claude se configurado, Gemini como fallback
    final_text = ""
    try:
        if ANTHROPIC_API_KEY and not audio_bytes:
            # Se for texto e a chave do Claude estiver no .env, usa Claude
            final_text = _process_with_claude(user_text=user_text or "", system_prompt=system_prompt, history=history)
        elif GEMINI_API_KEY:
            # Se for áudio ou se o Claude não estiver configurado, usa Gemini
            final_text = _process_with_gemini(
                user_text=user_text,
                audio_bytes=audio_bytes,
                mime_type=mime_type,
                system_prompt=system_prompt,
                history=history
            )
        else:
            return "❌ Nenhuma chave de API configurada (configure ANTHROPIC_API_KEY ou GEMINI_API_KEY no .env)."
    except Exception as e:
        # Se um falhar por cota ou rede, tenta o outro automaticamente
        err_msg = str(e)
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            if ANTHROPIC_API_KEY and not audio_bytes:
                final_text = _process_with_claude(user_text=user_text or "", system_prompt=system_prompt, history=history)
            else:
                return f"⚠️ Limite de requisições temporariamente excedido: {err_msg}"
        else:
            raise e

    # Grava na memória persistente
    append_message("user", recorded_user_message, user_id=user_id)
    append_message("model", final_text, user_id=user_id)

    return final_text
