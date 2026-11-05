# Gemensam Traefik-proxy

Fristående Docker Compose-stack för `utbildningsintyg.se` och `kursplan.se`. Traefik hanterar port 80/443, HTTPS och routning. Varje applikation kör sin egen Compose-stack.

## Mappstruktur på produktionsservern

```text
/opt/traefik/
├── docker-compose.yml
├── update.py
└── dynamic/
    └── tls.yml
```

Följande filer ska finnas på **servern**, inte i GitHub:
- `/etc/ssl/cloudflare/origin.crt` och `/etc/ssl/cloudflare/origin.key` för utbildningsintyg.se
- `/etc/ssl/cloudflare/kursplan.crt` och `/etc/ssl/cloudflare/kursplan.key` för Kursplan när denna domän aktiveras

Kontrollera var utbildningsintygets nuvarande origin-certifikat ligger (dess Compose använder `ORIGIN_CERT_PATH` och `ORIGIN_KEY_PATH`), och att rätt filpar kopierats säkert innan den gamla proxyn stoppas. Privata nycklar får aldrig committas.

## Förberedelser

1. Kontrollera nätverket: `docker network inspect jk_public_net`. Om det saknas, skapa det *en gång* med `docker network create jk_public_net`. Behåll nätverket även när appar stoppas.
2. Kontrollera att applikationerna ansluter sina webbcontainrar till det externa nätverket `jk_public_net`. Deras databaser bör stanna på interna nätverk.
3. Kontrollera att labels på utbildningsintygets app fortfarande refererar till `websecure`, `security-headers@file`, `upload-buffer@file` och appens interna port 80.
4. Kontrollera certifikatfilerna och deras behörigheter på värdservern.
5. Kontrollera Compose-syntax: `docker compose config --quiet`.

## Säker migrering från utbildningsintygets nuvarande Traefik

**Den gamla och den nya proxyn får inte lyssna på port 80/443 samtidigt.** Planera ett kort underhållsfönster och dokumentera vilka tjänster som körs före förändringen.

Stanna endast gamla `traefik`-tjänsten från den gamla utbildningsintyg-projektkatalogen, *innan* dess Compose-definition tas bort från den körande servern:

```bash
docker compose stop traefik
```

Starta nya Traefik från den fristående katalogen:

```bash
cd /opt/traefik
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose logs --tail=100 traefik
curl -I https://utbildningsintyg.se
```

Kontrollera även MTA-STS och befintlig inloggning i utbildningsintyg. Om migreringen misslyckas, stoppa nya proxyn och starta gamla proxyn igen med dess tidigare Compose-konfiguration. Bevara gamla containern/configen tills övergången är verifierad.

**Kör inte `docker compose down -v` eller `docker volume prune` på produktionsservern.** Flytta inga databasvolymer.

## Aktivera Kursplan

1. Lägg till A-post för `kursplan.se` och CNAME för `www` i Cloudflare, till samma origin som utbildningsintyg.se.
2. Installera ett separat Cloudflare Origin CA-certifikat för `kursplan.se` och `www.kursplan.se`, och använd SSL-läge **Full (strict)**.
3. Spara certifikatfilerna i `/etc/ssl/cloudflare/` och aktivera de kommenterade certifikatraderna i `dynamic/tls.yml`.
4. Anslut endast Kursplans webbcontainer till `jk_public_net`. Ange Traefik-labels för `Host(`kursplan.se`)`, `www.kursplan.se`, `websecure`, TLS och appens interna port `8000`. Publicera inte webbporten eller databasporten på värden.

## Daglig drift

```bash
cd /opt/traefik
docker compose ps
docker compose logs --tail=100 traefik
docker compose pull
docker compose up -d
```

`update.py` gör en fast-forward Git-uppdatering och `docker compose pull` följt av `docker compose up -d`, utan ett separat `down`-steg. Traefik kan fortfarande startas om vid en uppdatering, så det kan uppstå ett kort avbrott.

Traefiks dashboard är inte publicerad. För att öka säkerheten ytterligare bör direkt åtkomst till origin filtreras i brandvägg när Cloudflare används. Docker-socket med `:ro` är **inte** en behörighetsbegränsad Docker API-anslutning; överväg en begränsad socket-proxy.
