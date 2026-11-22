# Filtro de notificações

Copie para data/notificacoes-regras.md. Regras fixas, uma por linha, de dois tipos:
- "- endereco@exemplo.com": tudo desse remetente;
- "- endereco@exemplo.com | trecho do assunto": desse remetente, quando o assunto contém o trecho.
Elas valem antes de tudo e não passam pelo Gemini; remetente + assunto vence só remetente. Os botões de correção
no Telegram propõem uma regra ou uma frase de critério e só gravam depois do seu "sim". As frases aceitas
entram no fim de "Critérios", em "Correções do usuário".

## Avisar na hora

## Resumo diário

## Silêncio

## Critérios

Avisar na hora:
- Uma pessoa (não um sistema automático) escrevendo direto para o usuário e esperando resposta.
- Prazo ou vencimento para hoje ou amanhã.
- Problema com dinheiro: cobrança recusada, fatura atrasada, Pix ou compra não reconhecidos.
- Segurança da conta: login novo, senha trocada, dispositivo adicionado.
- Faculdade ou trabalho com prazo, mudança de aula ou de prova.

Resumo:
- Recibos, confirmações de compra, entregas a caminho, faturas sem atraso, avisos de serviço.
- Newsletters de pessoas ou projetos que o usuário segue.

Silêncio:
- Marketing, ofertas, "sentimos sua falta", notificações de redes sociais.
- Códigos de verificação (o usuário já está esperando por eles na tela).

Na dúvida entre dois níveis, escolha o mais alto: um alarme falso custa menos que um urgente perdido.
