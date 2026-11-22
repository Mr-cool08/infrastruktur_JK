# Järnvägskonsulterna – gemensam serverinfrastruktur

Detta repository är avsett för **gemensam infrastruktur** på Docker-servern. Applikationerna **utbildningsintyg.se**, **kursplan.se** och det interna systemet **JKA** förvaltas och driftsätts i egna projekt. Gemensam trafik in till webbapplikationerna ska hanteras av **Cloudflare Tunnel (cloudflared)** i stället för en egen publik Traefik-proxy.

> **Status (2026-11-09): målarkitektur för Cloudflare Tunnel.** Compose-filen ansluter cloudflared till de externa nätverken `jk_tunnel_net` och `jk_private_net`. Nätverken, applikationernas anslutningar och Cloudflare-rutterna behöver finnas i driftmiljön.

## 1. Översikt

~~~text
Besökare
   |
   | HTTPS (SSL-certifikat hos Cloudflare)
   v
Cloudflare (DNS, TLS, skydd och Access för interna tjänster)
   |
   | Krypterad, utgående Cloudflare Tunnel
   v
cloudflared (gemensam Docker Compose-stack)
   |                                  |
   | jk_tunnel_net                    | jk_private_net
   |                                  |
   +--> utbildningsintyg (webb)       +--> JKA (intern webb)
   |          |                                |
   +--> kursplan (webb)                       +--> jka_backend --> DB
              |
              +--> respektive app_backend --> respektive DB
~~~

- **En tunnel kan publicera flera domäner och applikationer.** Ingen ny tunnel behövs per tjänst.
- En enda cloudflared-container kan anslutas till båda de gemensamma Docker-nätverken.
- Varje applikation har en **egen Compose-stack** och ett **eget internt backend-nät** för exempelvis databas, cache och arbetare.
- En databas ska **aldrig anslutas till ett delat tunnelnät** eller få en publicerad host-port.
- JKA ska ligga på ett annat delat nät än de publika apparna och **skyddas med Cloudflare Access innan dess hostname publiceras**.
- Nätverkstillhörighet är inte en ersättning för autentisering eller behörighetskontroller.

## 2. Docker-nätverk

| Nätverk | Skapas av | Anslutna containrar | Syfte |
| --- | --- | --- | --- |
| `jk_tunnel_net` | Manuellt, en gång | `cloudflared`, utbildningsintygets och Kursplans webbcontainrar | Publika webbappar via tunneln |
| `jk_private_net` | Manuellt, en gång | `cloudflared`, JKA:s webbcontainer | Intern webbapp med Cloudflare Access |
| `utbildningsintyg_backend` | Utbildningsintygets Compose | Dess webb/backend och databas | Endast applikationens interna trafik |
| `kursplan_backend` | Kursplans Compose | Dess webb/backend och databas | Endast applikationens interna trafik |
| `jka_backend` | JKA:s Compose | JKA:s webb/backend och databas | Endast applikationens interna trafik |

Namnen på backend-nätverken uppstår om Compose-projekten heter `utbildningsintyg`, `kursplan` respektive `jka` och det lokala nätet i varje projekt heter `backend`.

Skapa **endast de delade nätverken manuellt** på servern:

~~~bash
docker network create jk_tunnel_net
docker network create jk_private_net

docker network inspect jk_tunnel_net
docker network inspect jk_private_net
~~~

Compose ska använda `external: true` för dessa två nätverk. Då försöker inte varje projekt skapa eller ta bort dem. De lokala backend-nätverken deklareras däremot i varje app som `internal: true` och skapas automatiskt.

**Observera:** Alla containrar på samma delade nät kan i princip nå varandra. `jk_tunnel_net` isolerar alltså **inte** utbildningsintyg från Kursplan. Krävs starkare avskiljning kan varje publik app få ett eget nät som cloudflared också ansluts till.

## 3. Gemensam Cloudflare Tunnel

**Målkonfiguration** för infrastrukturen (exempel; motsvarande ändringar behöver göras i den faktiska Compose-filen vid migrering):

~~~yaml
name: cloudflare-tunnel

services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel --no-autoupdate run --token ${TUNNEL_TOKEN:?Ange TUNNEL_TOKEN i .env}
    networks:
      - tunnel
      - private

networks:
  tunnel:
    external: true
    name: jk_tunnel_net
  private:
    external: true
    name: jk_private_net
~~~

Tunnel-token läggs i en **lokal `.env`** som inte checkas in i Git:

~~~dotenv
TUNNEL_TOKEN=ersatt-med-verklig-token
~~~

Token är en hemlighet: den som har den kan ansluta en connector till tunneln. Ge `.env` lämpliga filbehörigheter och se till att den är exkluderad från versionshantering.

Ingen `ports:`-mappning behövs för cloudflared. Tunneln initieras **utgående** från servern och kräver inte att inkommande TCP 80/443 öppnas för apparna. Tillåt nödvändig utgående trafik till Cloudflare (bland annat port 7844).

## 4. Hur applikationernas Compose-filer ska anslutas

Följande är **principmallar, inte exakta ändringar av andra repositories**. Befintliga image-namn, portar, env-variabler, volymer, databaser och startkommandon ska bevaras och anpassas i respektive projekt.

**Publik webbapp (utbildningsintyg; samma princip för Kursplan):**

~~~yaml
name: utbildningsintyg

services:
  web:
    # Befintlig image/build och övrig konfiguration behålls
    networks:
      tunnel:
        aliases:
          - utbildningsintyg
      backend:

  db:
    # Befintlig databaskonfiguration och volymer behålls
    networks:
      - backend

networks:
  tunnel:
    external: true
    name: jk_tunnel_net
  backend:
    internal: true
~~~

Kursplan ansluter i stället sin webbcontainer till `jk_tunnel_net` med det **unika aliaset** `kursplan` och använder ett lokalt `backend`-nät. Använd aldrig ett generiskt DNS-namn såsom `web` i tunnelrutter när flera projekt delar nätverk; samma tjänstenamn kan finnas i flera projekt.

**Intern app (JKA):**

~~~yaml
name: jka

services:
  web:
    # Befintlig PHP-webbserver och övrig konfiguration behålls
    networks:
      private:
        aliases:
          - jka
      backend:

  db:
    # Endast om JKA har en separat databascontainer
    networks:
      - backend

networks:
  private:
    external: true
    name: jk_private_net
  backend:
    internal: true
~~~

JKA ansluts **inte** till `jk_tunnel_net`. Om JKA kör PHP-FPM utan egen HTTP-server behövs Nginx/Apache eller motsvarande framför PHP-FPM innan tunneln kan nå den över HTTP.

**Grundregler:**

1. Endast containrar som ska ta emot HTTP från cloudflared ansluts till delat tunnelnät.
2. Databaser, Redis och interna arbetare ansluts endast till respektive backend-nät (eller särskilda privata appnät vid behov).
3. Ta bort onödiga `ports:` på värdservern. `expose:` publicerar inte en host-port och är inte i sig ett åtkomstskydd.
4. Konfigurera korrekt hantering av `Host` och proxy-/HTTPS-headers i webbapparna. Lita endast på betrodda proxies.
5. Behåll befintliga databasvolymer och databasversioner vid nätverksmigreringen.

## 5. Domänrutter i Cloudflare

I Cloudflares kontrollpanel: **Networking → Tunnels → [vald tunnel] → Routes → Add route → Published application**. Ange hostname och Service URL.

| Publikt hostname | Service URL från cloudflared | Skydd |
| --- | --- | --- |
| `utbildningsintyg.se` | `http://utbildningsintyg:8000` | Publik webbapp |
| `www.utbildningsintyg.se` | `http://utbildningsintyg:8000` | Publik webbapp / önskad redirect |
| `kursplan.se` | `http://kursplan:3000` | Publik webbapp |
| `jka.kursplan.se` **(förslag, ej beslutad adress)** | `http://jka:80` | **Cloudflare Access krävs** |

**Portarna är exempel.** Ersätt dem med respektive webbcontainers faktiska interna HTTP-port. Ett internt Docker-DNS-alias fungerar från cloudflared om containrarna delar rätt nätverk.

När en publicerad applikationsrutt läggs till via Cloudflares dashboard kan den associerade DNS-posten skapas automatiskt mot tunneln. Skapa inte en vanlig A-post som pekar direkt på serverns publika IP för en tunnelansluten tjänst.

Om en frontend och ett API har olika interna adresser behöver routning efter hostname/sökväg planeras separat, eller hanteras av en liten intern HTTP-router. Se också till att befintliga specialrutter, exempelvis `mta-sts.utbildningsintyg.se/.well-known/mta-sts.txt`, fungerar efter övergången.

## 6. SSL/TLS och åtkomst

Användaren ansluter med **HTTPS till Cloudflare**, som hanterar och automatiskt förnyar det publika edge-certifikatet (normalt Universal SSL). **Cloudflare → cloudflared** använder en krypterad tunnel. På samma isolerade Docker-värd kan **cloudflared → webbcontainer** använda vanlig HTTP på det interna Docker-nätet. Inget separat publikt Let's Encrypt- eller Cloudflare Origin CA-certifikat behövs då på appcontainern.

Om trafiken mellan cloudflared och webbapplikationen går över ett annat nät eller en annan server bör även den sista anslutningen krypteras med HTTPS och korrekt certifikatverifiering. Cloudflare-certifikatet på edge betyder inte att den sista hoppen automatiskt använder TLS.

**JKA:** Skapa en Cloudflare Access-applikation med en **deny-by-default**-policy som endast medger uttryckligen godkända användare eller grupper, helst med MFA. Publicera inte JKA:s rutt förrän åtkomstpolicyn är testad. Behåll även JKA:s egen inloggning och behörighetskontroll. Ett privat Docker-nät gör inte ett publikt hostname privat.

## 7. Migreringsordning och verifiering

1. Dokumentera nuvarande fungerande konfiguration samt vilka tjänster, portar och volymer som används. Säkerställ återställningsplan och backup.
2. Skapa `jk_tunnel_net` och `jk_private_net` (bara om de saknas).
3. Anpassa **infrastrukturprojektets** cloudflared-Compose till de externa näten. Kontrollera med `docker compose config --quiet`.
4. Anslut varje applikations webbcontainer till rätt delat nät och behåll databasen på appens egna backend-nät. Verifiera verkliga portar och nätverksalias.
5. Skapa/konfigurera tunneln och dess rutter i Cloudflare. Sätt upp och testa Access **innan** JKA exponeras.
6. Växla över respektive domän kontrollerat och testa webbläsare, inloggningar, API, uppladdningar, säkerhetsheaders, HTTPS och MTA-STS där tillämpligt.
7. När allt är verifierat kan gammal direkt exponering av 80/443 och tidigare Traefik-konfiguration tas bort. Behåll möjlighet till rollback tills migreringen godkänts.

Användbara kontroller på servern:

~~~bash
docker compose config --quiet
docker compose ps
docker compose logs --tail=100 cloudflared
docker network inspect jk_tunnel_net
docker network inspect jk_private_net
curl -I https://utbildningsintyg.se
curl -I https://kursplan.se
~~~

Kontrollera också att JKA från en **icke behörig** klient möts av Access-inloggning/nekad åtkomst och att databasportar inte är publicerade.

**Kör inte `docker compose down -v` eller `docker volume prune` under migreringen.** Det kan radera data.

## 8. Ansvarsfördelning

- **Detta repository:** gemensam cloudflared-stack, gemensamma nätverkskonventioner, värdserverns Fail2ban-konfiguration för SSH och uppdateringsrutiner.
- **Utbildningsintyg/Kursplan/JKA:** sina egna Compose-projekt, applikationskonfigurationer, databasvolymer, migreringar, tester och uppdateringar.
- **Cloudflare-kontrollpanelen:** tunnel, publicerade hostname-rutter, DNS, edge-certifikat och Access-policyer.

## 9. Fail2ban för SSH på värdservern

Fail2ban körs i samma Compose-projekt som cloudflared på Linuxvärden. Den monterar värdens systemd-journal skrivskyddat och använder värdnätverket för att lägga blockeringsregler i brandväggens `INPUT`-kedja. Regeln i `fail2ban/jail.d/sshd-jk.local` blockerar nya anslutningar till port `22` i en timme efter fem matchande fel från samma IP-adress inom tio minuter. Fail2bans databas sparas i Compose-volymen `fail2ban_data`.

Kör uppdateringen på Linuxvärden där OpenSSH skriver till systemd-journalen och Docker har åtkomst till värdens nätverk och brandvägg. Anpassa regelns `port` om OpenSSH använder en annan port. Om en befintlig Fail2ban-instans redan hanterar värdens SSH ska dess `sshd`-regel avaktiveras före övergången, så att en instans äger SSH-blockeringarna.

Vid den första uppdateringen från den äldre versionen, hämta det nya skriptet och kör det på värden.

~~~bash
git pull --ff-only
python3 update.py
~~~

Vid senare uppdateringar räcker `python3 update.py`. Skriptet hittar värdens aktuella systemd-journal i `/var/log/journal` eller `/run/log/journal`, hämtar avbilderna, väntar på att Compose-tjänsterna blir redo, laddar om SSH-regeln och kontrollerar dess status. Ange `FAIL2BAN_JOURNAL_DIR` i kommandots miljö om du behöver välja journalens sökväg manuellt.

Behåll din befintliga SSH-session öppen vid första uppdateringen och testa därefter en ny SSH-inloggning. Kontrollera status och loggar vid behov.

~~~bash
docker compose exec -T fail2ban fail2ban-client status sshd
docker compose logs --tail=100 fail2ban
~~~

För att pausa SSH-skyddet, kör `docker compose stop fail2ban`. Nästa körning av `update.py` startar tjänsten igen.

### Referenser

- [Cloudflare Tunnel – publicera appar och rutter](https://developers.cloudflare.com/tunnel/concepts/routing/)
- [Cloudflare Tunnel – kom igång](https://developers.cloudflare.com/tunnel/get-started/)
- [Cloudflare Access – skydda interna webbapplikationer](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
- [Docker Compose – nätverk över flera Compose-projekt](https://docs.docker.com/compose/how-tos/networking/)
- [Fail2ban – Compose-exempel med systemd-journal](https://github.com/crazy-max/docker-fail2ban/tree/master/examples/systemd)
