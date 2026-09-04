# O que pedir para quem administra o servidor

Você não tem (nem precisa de) acesso ao servidor. Duas coisas para pedir ao
administrador, uma vez cada:

## 1. Virar um peer WireGuard

Gere seu par de chaves (comando na seção
["Conectividade" do README](../README.md#conectividade)) e mande **só a
chave pública** para o administrador — a privada nunca sai da sua máquina.
Ele te devolve o IP que você ganhou na VPN (ex: `10.10.0.5`) e o endereço
público do servidor — é isso que você usa em `bridgectl init` como "endereço
que a ponte usa pra falar com o Synapse" (`http://10.10.0.1:8008`, o IP do
servidor na VPN, não o seu).

## 2. Registrar sua ponte

Depois de `bridgectl setup <ponte>`, mande pro administrador o
`registration.yaml` que ele gerou (`~/.config/mautrix-bridges/<ponte>/registration.yaml`
— já sai da sua máquina sem segredo em texto puro: o `bridgectl` já moveu os
tokens pro chaveiro antes). Ele registra do lado dele e te avisa quando
estiver pronto. Só então rode:

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

Gere um token de acesso **dedicado** pra ponte (não copie o token que o seu
Element já está usando agora — usar o mesmo token em dois lugares causa
problema de sincronização de chaves de criptografia):

```bash
curl -XPOST -d '{"type":"m.login.password","identifier":{"type":"m.id.user","user":"seu_usuario"},"password":"sua_senha","initial_device_display_name":"bridge-whatsapp"}' \
  https://seu-dominio.com/_matrix/client/v3/login
```

(Se você só usa SSO, veja o passo "Manualmente com SSO" na
[doc oficial](https://docs.mau.fi/bridges/general/double-puppeting.html).)

Isso devolve um `access_token`. Na sala de gerenciamento da ponte, mande:

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

### O que nenhum dos dois resolve

Nem o método manual nem o automático mudam o fato de que quem administra o
servidor sempre pode agir como qualquer conta hospedada nele — isso é
inerente a usar um servidor que você não controla, não uma falha de
configuração de double puppeting.

## Checklist rápido por ponte nova

- [ ] Chave pública WireGuard enviada, peer confirmado (`ping` no IP do
      servidor funciona)
- [ ] `bridgectl setup <ponte>` rodou sem erro
- [ ] `registration.yaml` enviado ao administrador e por ele confirmado
- [ ] `systemctl --user enable --now mautrix-bridge@<ponte>`
- [ ] Bot da ponte responde numa sala de teste
- [ ] (opcional) double puppeting configurado — manual (`login-matrix`) de
      preferência
