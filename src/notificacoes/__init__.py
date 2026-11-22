"""Filtro de notificações e e-mails (item 14 do AGENTS.md).

Fronteira inegociável: o texto de e-mails e notificações não é confiável e nunca chega ao agente que tem
ferramentas. Por isso este pacote não importa src.agent, src.history, src.mcp_server nem src.cli, e nenhum
deles importa este pacote (tests/test_notificacoes.py falha se isso mudar). O único contato do texto com um
modelo é o classificador, que roda sem nenhuma ferramenta e cuja saída é validada por código.

Módulos:
- db.py            SQLite com os itens recebidos, o estado (historyId, último resumo) e o uso diário do Gemini
- regras.py        arquivo de regras em data/ (remetentes fixos por nível + critérios em texto)
- gmail.py         leitura do Gmail só com gmail.readonly (cabeçalhos e snippet, nunca o corpo)
- classificador.py Gemini sem ferramentas, em lote, com saída validada
- pipeline.py      uma rodada: Gmail → regras → classificador → SQLite; e a montagem dos resumos
- telegram.py      alertas, resumos, botões de correção e balanço, enviados direto pela API do bot
"""
