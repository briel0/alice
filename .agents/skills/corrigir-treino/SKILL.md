---
name: corrigir-treino
description: Audita um treino registrado pela ALICE na API do Treinos, comparando com a conversa do Telegram e com o INBOX, e corrige o que ficou errado (séries perdidas ou confirmadas sem gravar, exercício fora do catálogo que foi para o INBOX, exercício trocado, carga e repetições invertidas). Use quando o usuário pedir "analisa/confere/corrige meu treino", disser que "ficou um exercício no inbox" ou que a ALICE "registrou errado".
---

# Corrigir treino

Primeiro **auditar** (só leitura), depois **corrigir** (só com o "ok" do usuário: mexe no banco de produção e no
`tarefas.md`). Tudo roda na VPS (`ssh alice-vm`); a API do Treinos escuta só em `127.0.0.1:5265`, sem autenticação.

## 1. Auditoria (só leitura)

Junte as três fontes do dia do treino. O dia é o de **São Paulo**: o `startedAt` vem em UTC, e um treino às 21h
aparece no dia seguinte em UTC.

1. **API:** `curl -s "http://127.0.0.1:5265/api/workouts?since=AAAA-MM-DD"`. Liste cada exercício com as séries
   (`loadKg`×`reps`, `type`, `isFailed`).
2. **Conversa:** `sudo -u alice grep -a "AAAA-MM-DDT" /opt/alice/app/data/historico.jsonl`, com as mensagens do usuário
   e as respostas da ALICE com horário.
3. **INBOX:** `sudo -u alice sed -n "/^## .*INBOX/,/^## /p" /opt/alice/app/data/tarefas.md`. Procure séries e
   exercícios que deveriam estar no treino.

Para alinhar mensagem com gravação:
- Os ids das séries são **UUID v7**: os 12 primeiros dígitos hexadecimais são o horário de criação em milissegundos.
  Assim dá para saber qual mensagem gerou cada série.
- `sudo journalctl -u treinos-api --since ... --until ...` mostra se uma requisição chegou mesmo. Isso prova uma
  **confirmação fantasma**: a ALICE respondeu "Registrei" e nenhum POST chegou.

Monte uma tabela **"você mandou × foi gravado × problema"** e procure estes erros, que já aconteceram:
- série confirmada ("Registrei mais 1 série… total de N") que não está na API, ou um total que não bate;
- exercício fora do catálogo que foi para o INBOX, às vezes duplicado;
- série seguinte gravada no exercício anterior ou trocada por um parecido (alternada virando rosca direta);
- correção do usuário não aplicada ("13 kgs" que eram 13 reps);
- aquecimento gravado como série de trabalho; o mesmo exercício partido em várias entradas.

Pergunte o que os dados não respondem (carga que não foi dita, se uma série era nova ou corrigia outra). Mostre o
plano de correção e **espere o ok**.

## 2. Exercício que não está no catálogo

A API **não cria exercícios**: o catálogo vem de `docs/exercise-catalog.json` (a fonte) e de uma migration por
exercício no repositório do Treinos (`~/projetos/ecossistema/treinos`). Siga a migration `feat(catalog)` mais recente.

1. Confira se já existe com outro nome: `curl -s "http://127.0.0.1:5265/api/exercises/resolve?term=..."` e a lista
   `/api/exercises`. Se for o mesmo movimento, use o existente.
2. Acrescente ao JSON: nome em pt-BR, `measurement_type`, `is_unilateral`, músculos primários e secundários (os 11
   grupos de lá) e apelidos em pt-BR e inglês.
3. `dotnet tool restore`, depois
   `dotnet ef migrations add <Nome> --project src/Treinos.Infrastructure --startup-project src/Treinos.Infrastructure --output-dir Persistence/Migrations`.
   O EF gera `Up`/`Down` vazios. Copie o SQL da migration de catálogo anterior: `INSERT` com `WITH ... RETURNING id`
   em `exercises`, `exercise_muscle_groups` e `exercise_aliases`, e o `Down` apagando por nome com `user_id IS NULL`.
   Mantenha o BOM e o fim de linha do arquivo vizinho.
4. `dotnet build` e `dotnet format --verify-no-changes` (e `dotnet test`, se der).
5. Script só desta migration, **com `-o`** (pela saída padrão vem a linha "Build started..." misturada no SQL):
   `dotnet ef migrations script <Anterior> <Nova> --idempotent ... -o arquivo.sql`. Ponha `SET search_path = treinos;`
   na primeira linha e **tire o BOM** (`sed -i 's/\xEF\xBB\xBF//g'`), porque o `psql` rejeita o BOM no meio do arquivo.
6. Aplique: `scp` para `/tmp`, depois `sudo -u treinos psql -v ON_ERROR_STOP=1 -d planner -f /tmp/arquivo.sql` (o
   schema `treinos` mora no banco `planner`). O `treinos_dev` é opcional, pelo túnel descrito no AGENTS.md do Treinos.
   A API **não** precisa de deploy, porque a mudança é só de dados. Confira com `resolve`.
7. Commit no repositório do Treinos (`feat(catalog): add ...`) só com aprovação do usuário.

## 3. Gravar as séries que faltam

- **Exercício novo no fim do treino:** `treinos.log_exercise` da própria ALICE, rodando na VPS como `alice`
  (`cd /opt/alice/app && .venv/bin/python -c "from src import treinos; print(treinos.log_exercise('nome', [{'reps': 10, 'load_kg': 20}], day='AAAA-MM-DD'))"`).
  Ela só **soma** à última entrada se for o mesmo exercício; senão cria uma entrada nova.
- **Série faltando num exercício do meio do treino:** `POST /api/workouts/{id}/exercises/{workoutExerciseId}/sets`
  com `{"sets": [...]}`. Exercício novo: `POST /api/workouts/{id}/exercises` com `{"id", "exerciseId", "sets"}`.
  Cada série leva `id` (UUID v7: `uuid.uuid7()` no Python 3.14), `type` (null = trabalho), `isFailed`, `reps`,
  `loadKg`, `assistanceKg`, `durationSec`, `distanceM` e `side`.
- **Exercício errado:** `DELETE /api/workouts/{id}/exercises/{workoutExerciseId}` e gravar de novo. A API **não
  reordena**: para manter a ordem original, regrave os exercícios seguintes e só depois apague as entradas antigas.
- Script gerado no Windows e mandado por `ssh ... 'bash -s' < script`: **converta para LF** antes. Com CRLF a URL
  ganha um `\r`, e o `curl` falha com código 000 sem gravar nada.
- **Sempre leia o treino de volta** (`GET /api/workouts/{id}`) e mostre a tabela final. Nunca declare corrigido sem
  essa leitura: o erro que se está corrigindo é justamente confirmar sem conferir.

## 4. INBOX e fechamento

- Marque ou tire do INBOX os itens resolvidos, como `alice` e dentro de `data/` (`sudo -u alice sh -c "cd /opt/alice/app/data && ..."`),
  e faça um commit no repositório de dados. Não use `cd` fora do `sudo`: o diretório é fechado para outros usuários.
- Se a causa for um bug da ALICE, aponte o item do backlog no AGENTS.md (confirmação fantasma: item 22; exercício
  fora do catálogo: item 23) e acrescente o caso novo ali, com data.
