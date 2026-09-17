# O que pedir para quem administra o servidor

Você não tem (nem precisa de) acesso ao servidor. Duas coisas para pedir ao
administrador, uma vez cada:

## 1. Virar um peer WireGuard

Gere seu par de chaves (comando na seção
["Conectividade" do README](../README.md#conectividade)) e mande **só a
chave pública** para o administrador — a privada nunca sai da sua máquina.
Ele te devolve o IP que você ganhou na VPN (ex: `10.10.0.5`) — é isso que
você usa em `bridgectl init` como "seu IP nesta VPN". O "endereço público do
Synapse" é outra pergunta do `init`, e é a URL HTTPS normal (a mesma que seu
Element usa) — não tem relação com a VPN, é tráfego de saída comum.

## 2. Registrar sua ponte

Depois de `bridgectl setup <ponte>`, rode:

```bash
bridgectl reveal <ponte> --out registration-para-o-admin.yaml
```

O arquivo em `~/.config/mautrix-bridges/<ponte>/registration.yaml` fica só
com placeholder do chaveiro (`${keyring:...}`) — o Synapse não entende isso,
precisa do valor real, por isso o `reveal` existe: gera na hora uma cópia com
os valores de verdade, só pra essa entrega. Mande esse arquivo pro
administrador e **apague-o em seguida** (ele volta a ter segredo em texto
puro, é descartável por natureza). Ele registra do lado dele e te avisa
quando estiver pronto. Só então rode:

```bash
systemctl --user enable --now mautrix-bridge@<ponte>
journalctl --user -u mautrix-bridge@<ponte> -f
```

## 3. Double puppeting (opcional, mas recomendado)

Sem isso, mensagens que você manda direto do WhatsApp/Slack aparecem no Matrix
vindas de um "fantasma" (`@slack_você:seu-dominio`) em vez da sua conta de
verdade. Duas formas — a manual não depende do administrador pra nada além
do que você já pediu acima.

### Manual (recomendado): você mesmo faz, sem pedir nada a mais

Este servidor delega login pro matrix-authentication-service (MAS) — não
existe `m.login.password` aqui, só SSO (Google). Gere um token de acesso
**dedicado** pra ponte (não copie o token que o seu Element já está usando
agora — usar o mesmo token em dois lugares causa problema de sincronização
de chaves de criptografia):

Element → Configurações → Ajuda e sobre → Avançado → Access Token → revele
e copie. **Atenção**: esse token é de curta duração sob MAS (confirmado
nesta sessão — expira bem antes do que se esperaria de um token "normal"
do Matrix) e pode até devolver `M_UNKNOWN_TOKEN (HTTP 401): Token is not
active` já na primeira tentativa de uso sob carga do homeserver — se isso
acontecer, tente de novo em alguns segundos antes de assumir que o token
está errado. Se ele expirar com frequência, peça ao administrador do
servidor pra gerar um token de longa duração de verdade com
`mas-cli manage issue-compatibility-token <seu_usuario> <device_id>`
(exige acesso de admin ao MAS, então só ele pode rodar isso).

Isso devolve um `access_token` (ou o token que você copiou do Element). Na
sala de gerenciamento da ponte, mande:

```
login-matrix <o access_token>
```

Um `login-matrix` por ponte (cada uma precisa do seu próprio token/dispositivo
— reusar o mesmo token em duas pontes ao mesmo tempo tem o mesmo problema de
sincronização citado acima). Guarde o token no chaveiro se quiser reenviá-lo
depois (`bridgectl set <ponte> matrix_token`), mas ele só representa a **sua**
conta — não existe segredo nenhum aqui com poder sobre a conta de outra
pessoa. Se o token for revogado (deslogar todos os dispositivos, trocar
senha), a ponte só perde o double puppeting até você repetir o `login-matrix`
— nada mais quebra.

### Automático: menos trabalho manual, mas pede um registro a mais ao administrador

Existe um jeito de a ponte pegar o token sozinha, sem você rodar
`login-matrix` toda vez que o token expirar — mas exige que o administrador
registre **um segundo appservice** (mesmo processo do item 2 acima, outro
arquivo) cujo namespace, por natureza, precisa cobrir contas além dos
fantasmas da ponte. Peça a ele pra restringir esse appservice à(s) sua(s)
conta(s) especificamente (`@voce:dominio`), nunca a um curinga (`@.*:dominio`)
— um curinga nesse appservice dá a quem tiver o token dele o poder de se
passar por **qualquer** conta do servidor, não só a sua. Depois, no
`config.yaml` da sua ponte:

```yaml
double_puppet:
  secrets:
    seu-dominio.com: "as_token:<o as_token que o administrador te passar>"
```

Leve esse valor pro chaveiro (`bridgectl harvest` ou `bridgectl set <ponte>
dp_secret`) e trate-o como mais sensível que o `as_token` da sua própria
ponte — ele pode agir como qualquer conta que o administrador tiver incluído
no namespace dele.

### Pontes legadas (mautrix-discord, por exemplo): o manual funciona, só o automático que não

`login-matrix`/`logout-matrix`/`ping-matrix` são comandos genéricos do
próprio framework mautrix-go, não algo exclusivo do bridgev2 — confirmado
lendo os símbolos do binário instalado (`mautrix-discord` v0.7.7): as três
strings de comando e as mensagens de uso/confirmação (`` `login-matrix
<access token>` ``, "Confirmed valid access token for...", "You don't have
double puppeting enabled.") estão todas lá. Uma versão desta doc chegou a
dizer o contrário — estava desatualizada, corrigido aqui. O que essas pontes
legadas **não têm** é o método automático de appservice de namespace restrito
descrito acima (esse sim é exclusivo do bridgev2). Pra elas, o único jeito
automático disponível é ainda mais amplo que o `as_token` de namespace
restrito: usa um segredo único do Synapse inteiro
([`matrix-synapse-shared-secret-auth`](https://github.com/devture/matrix-synapse-shared-secret-auth))
que autentica como **qualquer conta que já exista no servidor**, sem
distinção nenhuma por namespace — não dá pra restringir a uma conta
específica como no método `as_token`. Não recomendamos usar isso: o ganho
(não precisar rodar `login-matrix` de novo quando o token expirar) não
compensa colocar uma chave-mestra do servidor dentro do `config.yaml` da
ponte, que fica em texto claro no seu computador. Use o método manual acima
mesmo nessas pontes — funciona igual.

### O que nenhum dos dois resolve

Nem o método manual nem o automático mudam o fato de que quem administra o
servidor sempre pode agir como qualquer conta hospedada nele — isso é
inerente a usar um servidor que você não controla, não uma falha de
configuração de double puppeting.

## 4. A "chave de recuperação" que o Element pede (backup de criptografia)

Em algum momento o Element mostra algo como *"Your chats are automatically
backed up with end-to-end encryption. To restore this backup... you will
need your recovery key"*. **Isso não tem nada a ver com o chaveiro do
bridgectl, com a senha da sua conta, nem com nenhum token de ponte** — é o
backup de chaves de criptografia ponta-a-ponta do próprio Matrix/Element,
independente de você usar ponte ou não. É só mais uma coisa dessas que
aparece justamente quando você começa a usar salas de ponte (que podem vir
criptografadas), por isso a confusão de achar que é algo do bridgectl.

Por que isso importa quando você usa pontes:

- **Se as salas da ponte forem criptografadas**, elas seguem a mesma regra
  de qualquer sala do Matrix: sem a chave de recuperação, se você perder
  acesso a todos os seus dispositivos de uma vez, o histórico de mensagens
  anterior fica **irrecuperável para sempre** — não existe "esqueci minha
  senha" pra isso.
- **Double puppeting (seção 3) faz a ponte agir como mais um "dispositivo"
  logado como você.** Mais dispositivos por conta é mais chance de alguma
  sincronização de chave falhar e aparecer "não foi possível decifrar a
  mensagem" (UTD) numa sala ou outra — normalmente se resolve sozinho depois
  de um tempo, mas ter o backup configurado ajuda a se recuperar quando não
  resolve.

**Recomendação**: configure a chave de recuperação quando o Element pedir
(ou em Configurações → Segurança e privacidade) e guarde-a num gerenciador
de senhas — ela é um quarto tipo de segredo nesse sistema todo, diferente
de tudo mais: não é sua senha do Matrix, não é o token de double puppeting,
não é nada que passa pelo chaveiro do bridgectl. Perdê-la não tira seu
acesso à conta — só a capacidade de recuperar histórico criptografado
antigo caso você perca todos os dispositivos de uma vez.

## Checklist rápido por ponte nova

- [ ] Chave pública WireGuard enviada, peer confirmado (`ping` no IP do
      servidor funciona)
- [ ] `bridgectl setup <ponte>` rodou sem erro
- [ ] `registration.yaml` enviado ao administrador e por ele confirmado
- [ ] `systemctl --user enable --now mautrix-bridge@<ponte>`
- [ ] Bot da ponte responde numa sala de teste
- [ ] (opcional) double puppeting configurado — manual (`login-matrix`) de
      preferência
- [ ] marcador de plataforma, space geral e criptografia já vieram
      aplicados automaticamente pelo `setup` (ver README.md § Uso) — nada
      a fazer aqui, exceto conferir se quer ajustar o histórico
      (perguntado no próprio `setup`)
- [ ] chave de recuperação do Element configurada e guardada num gerenciador
      de senhas (seção 4) — não é segredo do bridgectl, mas evite deixar pra
      configurar depois de já ter histórico criptografado acumulado
