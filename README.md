# Gemensam Traefik-proxy

Fristående Docker Compose-stack för `utbildningsintyg.se` och `kursplan.se`. Den gemensamma Traefik-instansen hanterar port 80/443, TLS-certifikat, domänrouting och gemensamma säkerhetsregler. Varje applikation behåller sin egen Compose-stack och separata databasnätverk.

## Mappstruktur på produktionsservern

```text
/opt/traefik/
├── docker-compose.yml
├── update.py
└── dynamic/
    ├── tls.yml                 # certifikat och återanvändbara middlewares
    └── utbildningsintyg.yml    # domäner, HTTPS, MTA-STS och backend
```

Följande filer ska finnas **endast på servern**, inte i GitHub:

- `/etc/ssl/cloudflare/origin.crt` och `/etc/ssl/cloudflare/origin.key` för utbildningsintyg.se (inklusive www och mta-sts).
- `/etc/ssl/cloudflare/kursplan.crt` och `/etc/ssl/cloudflare/kursplan.key` när Kursplan aktiveras.

Kontrollera var utbildningsintygets nuvarande certifikat ligger innan den gamla proxyn stoppas. Privata nycklar får aldrig committas.

## Ägarskap och routing

- **Delade proxyn:** `dynamic/utbildningsintyg.yml` definierar routrarna `utbildningsintyg-web@file` och `utbildningsintyg-mta-sts@file`, HTTPS och referenser till middlewares i `dynamic/tls.yml`.
- **Utbildningsintyg-appens Compose:** ansluter webbcontainern till det externa nätverket `jk_public_net` med det stabila aliaset `utbildningsintyg-web`, och exponerar endast port 80 för andra containrar. Appen har **inga produktionslabels för Traefik**.
- **Backend:** Traefik skickar HTTP på Docker-nätverket till `http://utbildningsintyg-web:80`. Applikationen ska fortfarande ha `PREFERRED_URL_SCHEME=https`, `SESSION_COOKIE_SECURE=true` och korrekt `TRUSTED_PROXY_COUNT`.
- **MTA-STS:** den särskilda routern matchar enbart `mta-sts.utbildningsintyg.se/.well-known/mta-sts.txt`. Policyn levereras av appen; MTA-STS kräver ett publikt betrott HTTPS-certifikat sett från internet.
- **Kursplan:** Docker-providern behålls tills dess routing eventuellt flyttas till en central fil; den här ändringen påverkar inte Kursplans befintliga labels.

I `dynamic/utbildningsintyg.yml` har de nya routrarna tillfälligt `priority: 1`, så att utbildningsintygets äldre Docker-label-routrar fortsätter vinna om båda finns under migreringen. När labels tas bort ur appen används filroutrarna. Ta inte bort prioriteringen utan en separat granskning av överlappande routningsregler.

## Förberedelser

1. Kontrollera det gemensamma Docker-nätverket med `docker network inspect jk_public_net`. Skapa det bara om det saknas på en **ny** installation: `docker network create jk_public_net`.
2. Kontrollera att den gamla appens Docker-nätverk heter `jk_public_net` och att dess befintliga Traefik-labels fortfarande är aktiva under första steget. Databasen ska ligga på ett separat internt nätverk.
3. Kontrollera att certifikatfilerna och behörigheterna på värdservern är korrekta för samtliga berörda värdnamn. Behåll Cloudflare Full (strict), där Cloudflare används.
4. Kör `docker compose config --quiet` i proxykatalogen och kontrollera att `dynamic/utbildningsintyg.yml` och `dynamic/tls.yml` monteras in.
5. Kontrollera senaste databasbackup och spara gamla Compose-filen, monterad Traefik-konfiguration och gamla Git-revisioner. **Använd inte `docker compose down -v` eller `docker volume prune`.**

## Säker migrering (två separata pull requests)

**Viktigt:** Ändringen kräver både detta Traefik-repo och JK-utbildnings-intyg PR #530. Slå **inte** ihop och driftsätt appens PR före att den centrala routingfilen finns på proxyn. Allt arbete görs med bibehållna appdata och volymer.

1. **Starta den externa proxyn, med gammal appkonfiguration kvar.** Om utbildningsintyg fortfarande kör sin egen gamla Traefik, identifiera den och stoppa *endast* gamla proxycontainern innan nya proxyn tar port 80/443. Behåll gamla containern och dess filer för rollback. Starta från `/opt/traefik`:
   ```bash
   docker compose config --quiet
   docker compose up -d
   docker compose logs --tail=100 traefik
   ```
   Nya `@file`-routrar har lägre prioritet än den gamla appens `@docker`-routrar. Webbtrafiken ska därför fortfarande gå via befintliga labels under detta steg.
2. **Bekräfta att befintlig trafik fungerar.** Testa `https://utbildningsintyg.se/health`, `https://www.utbildningsintyg.se/health`, MTA-STS och normal inloggning. Kontrollera även proxyloggar och certifikat.
3. **Driftsätt sedan JK PR #530** i samma app-Compose-projekt och med samma `.env` och volymer som tidigare. Appen får nätverksaliaset `utbildningsintyg-web` och tappar sina tidigare Traefik-labels. Kontrollera att aliaset fungerar från proxyns nätverk samt `docker compose config --quiet` innan omstart. Återskapa enbart de containrar som verkligen behöver uppdateras.
4. **Verifiera den nya vägen:** HTTP 200 på `/health` för båda huvudvärdarna, rätt MTA-STS-policy på exakt sökväg, 404 för annan sökväg på MTA-STS-värden, HTTPS och säkerhetsheaders, samt inloggning/uppladdning. Kontrollera att den centrala proxyns loggar visar trafiken.
5. Återaktivera schemalagda uppdateringar först när båda förändringarna är verifierade. Ta bort gamla proxycontainern först när återställningsfönstret är stängt.

### Återställning

Om fel uppstår **innan** JK PR #530 driftsätts kan den nya proxyn stoppas och gamla proxyn startas med sin sparade konfiguration, utan ändringar i applikationens volymer.

Om fel uppstår **efter** att JK PR #530 driftsatts: återställ appens tidigare Git-version och Compose-definition **med oförändrat projektnamn, befintlig `.env` och befintliga volymer**. Återskapa appcontainern så att de gamla Traefik-labelsen återkommer, och kontrollera att befintlig `@docker`-routing fungerar igen. Om även själva proxyn behöver återställas, frigör först port 80/443 från den nya containern innan gamla startas. Använd aldrig `down -v` som rollback.

## Aktivera Kursplan

1. Ställ in rätt DNS-poster för `kursplan.se` och `www.kursplan.se` till servern.
2. Installera ett separat Cloudflare Origin CA-certifikat för dessa värdnamn och behåll **Full (strict)**.
3. Spara certifikatfilerna under `/etc/ssl/cloudflare/` och aktivera certifikatraderna i `dynamic/tls.yml`.
4. Anslut endast Kursplans webbcontainer till `jk_public_net`. Tills Kursplans routing centraliseras används dess befintliga Traefik-labels. Publicera inte webbporten eller databasporten direkt på värden.

## Daglig drift

```bash
cd /opt/traefik
docker compose ps
docker compose logs --tail=100 traefik
docker compose pull
docker compose up -d
```

`update.py` gör en fast-forward Git-uppdatering och `docker compose pull` följt av `docker compose up -d`, utan separat `down`. En Traefik-uppdatering kan fortfarande orsaka ett kort avbrott.

Traefiks dashboard är inte publicerad. Begränsa direkt åtkomst till origin i serverns brandvägg när Cloudflare används. Docker-socket med `:ro` är **inte** en behörighetsbegränsad Docker API-anslutning; överväg en begränsad socket-proxy.
