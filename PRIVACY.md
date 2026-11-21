# Política de privacidade da ALICE

A ALICE é um assistente pessoal de código aberto. Cada instalação é usada só pela pessoa que a instalou, com as próprias credenciais. Não existe serviço compartilhado nem outros usuários.

## Gmail

- A ALICE pede só o escopo `gmail.readonly`. Ela não envia, apaga, move nem marca e-mails como lidos.
- Ela lê só os cabeçalhos (remetente e assunto), a categoria e o trecho inicial que o Gmail fornece. O corpo das mensagens nunca é baixado.
- Esses dados ficam no servidor do próprio dono, por no máximo 30 dias, e servem só para decidir quais e-mails merecem aviso.
- Para classificar, o remetente, o assunto e o trecho são enviados à API do Google Gemini, sob a conta do próprio dono.
- Nada é vendido, compartilhado com terceiros ou usado para publicidade.

O uso de informações recebidas das APIs do Google segue a [Política de dados do usuário dos serviços de API do Google](https://developers.google.com/terms/api-services-user-data-policy), incluindo os requisitos de uso limitado.

Para revogar o acesso a qualquer momento: https://myaccount.google.com/permissions

---

ALICE is a self-hosted, single-user personal assistant. It requests only `gmail.readonly`, reads headers, category and the Gmail snippet (never message bodies), keeps them on the owner's own server for at most 30 days, sends them to the Google Gemini API only to classify relevance, and never shares or sells data. Use of information received from Google APIs adheres to the Google API Services User Data Policy, including the Limited Use requirements.
