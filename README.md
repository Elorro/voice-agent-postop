# Voice Agent Post-Op

Agente de voz en español para seguimiento postoperatorio.
**Tech Sphere Challenge 2026.**

**Modelo de lenguaje y compuerta G3:** los modelos de la lista permitida
servidos por Groq y Google fueron retirados por sus proveedores. Qué usa esta
solución y por qué cumple: **[`docs/DECLARACION_MODELO.md`](docs/DECLARACION_MODELO.md)**.

> **Estado: esqueleto levantable.** El contenedor arranca, carga sus modelos y
> reporta su estado componente por componente en `/salud`. El turno de voz, el
> STT, el LLM, el RAG y la consola clínica **todavía no están implementados**.
> Lo que se puede verificar hoy es exactamente eso: que levanta y que dice la
> verdad sobre sí mismo.

---

## 1. Requisitos previos

Hace falta **Docker con Compose v2**. Nada más: ni Python, ni modelos, ni
descargas manuales. Todo va dentro de la imagen.

| Sistema | Qué instalar | Mínimo |
|---|---|---|
| Linux | Docker Engine + plugin `docker-compose-plugin` | Engine 24, Compose v2 |
| macOS | Docker Desktop | 4.30 |
| Windows | Docker Desktop con backend **WSL2** | 4.30 |

### Verifíquelo antes de seguir

Ejecute los dos comandos de su sistema y compare con lo que debe salir. **Si el
segundo falla, ningún paso posterior va a funcionar**, y el mensaje de error no
se lo va a decir.

| Sistema | Comando | Debe responder |
|---|---|---|
| Linux | `sudo docker --version` | `Docker version 24.` o superior |
| Linux | `sudo docker compose version` | `Docker Compose version v2.` **o superior** |
| macOS | `docker --version` | `Docker version 24.` o superior |
| macOS | `docker compose version` | `Docker Compose version v2.` **o superior** |
| Windows | `docker --version` | `Docker version 24.` o superior |
| Windows | `docker compose version` | `Docker Compose version v2.` **o superior** |

Lo que **no** sirve:

- `docker-compose version` respondiendo `1.29.x` (con guion). Es Compose v1,
  está descontinuado y no entiende `compose.yaml`. La versión buena se invoca
  **sin guion**: `docker compose`. Si `docker compose version` da
  «is not a docker command», falta el plugin: instale
  `docker-compose-plugin` (Linux) o actualice Docker Desktop.
- Un `docker compose version` que responda `2.0.x` sirve, pero muy justo. Con
  Docker Desktop 4.30 o superior queda holgado.

---

## 2. Levantarlo

Cinco pasos. Elija su bloque y **copie los comandos tal cual**, en orden.
Cada bloque es autosuficiente: no mezcle comandos de un sistema con los de otro.

### Linux

`sudo` en **todos** los pasos, sin excepción.

```bash
git clone https://github.com/Elorro/voice-agent-postop.git
cd voice-agent-postop
cp .env.example .env
nano .env                       # pegue LLM_API_KEY y STT_API_KEY, guarde (Ctrl+O, Enter, Ctrl+X)
sudo docker compose pull
sudo docker compose up -d
xdg-open http://localhost:8080/salud
```

> **Por qué `sudo` y no el grupo `docker`.** Añadirse al grupo `docker`
> (`usermod -aG docker $USER`) **no toma efecto hasta cerrar la sesión y volver
> a entrar**. Ese paso es invisible: el comando parece haber funcionado, y el
> siguiente falla con «permission denied while trying to connect to the Docker
> daemon socket». `sudo` funciona siempre, desde el primer minuto.
>
> *Nota para quien ya pertenezca al grupo `docker` y haya reiniciado sesión:*
> puede omitir `sudo` en todos los comandos de este documento. Omítalo en
> todos o en ninguno; mezclarlo crea contenedores y volúmenes en dos contextos
> distintos que no se ven entre sí.

### macOS

Sin `sudo` en ningún paso. Docker Desktop debe estar corriendo (icono de la
ballena en la barra de menú).

```bash
git clone https://github.com/Elorro/voice-agent-postop.git
cd voice-agent-postop
cp .env.example .env
open -e .env                    # pegue LLM_API_KEY y STT_API_KEY, guarde (Cmd+S)
docker compose pull
docker compose up -d
open http://localhost:8080/salud
```

### Windows (PowerShell)

Sin `sudo` —no existe en Windows— y **sin** ejecutar como administrador. Docker
Desktop debe estar corriendo y con el backend WSL2 activo.

```powershell
git clone https://github.com/Elorro/voice-agent-postop.git
cd voice-agent-postop
Copy-Item .env.example .env
notepad .env                    # pegue LLM_API_KEY y STT_API_KEY, guarde (Ctrl+S), cierre
docker compose pull
docker compose up -d
Start-Process http://localhost:8080/salud
```

### Alternativa: construir en vez de descargar

Solo si `docker compose pull` falla (ghcr.io bloqueado, red corporativa). Tarda
bastante más porque baja los modelos y compila la imagen en su máquina:

```bash
sudo docker compose build      # Linux;  en macOS/Windows: docker compose build
sudo docker compose up -d
```

---

## 3. Confirmar que quedó bien

Abra **http://localhost:8080/salud**. La página muestra un veredicto grande y
una fila por componente.

> Si cambió `PUERTO` en `.env` —porque el 8080 estaba ocupado, ver §10— la
> dirección es `http://localhost:<PUERTO>/salud`, no el 8080. `PUERTO` es el
> puerto del **host**; dentro del contenedor el proceso escucha siempre en 8080.

| Lo que ve | Qué significa | Qué hacer |
|---|---|---|
| **LISTO** | Todos los componentes bloqueantes respondieron | Nada. Listo. |
| **NO LISTO** | Al menos uno falló | Lea la fila en rojo: dice cuál y por qué |

Lo que debe ver hoy, con la clave puesta:

| Componente | Estado esperado | Detalle |
|---|---|---|
| Índice vectorial | OK | `0 documentos (vacío: el indexador aún no existe)` |
| Embedder | OK | `cargado, 384 dimensiones` |
| Voz (Piper) | OK | `es_MX-ald-medium.onnx cargado (es_MX, 22050 Hz)` |
| LLM (modelo de lenguaje) | OK | `«meta-llama/llama-3.1-70b-instruct» servido y alcanzable (… ms) · perfil «remoto»` |
| STT (transcripción) | OK | `«whisper-large-v3» servido y alcanzable (… ms) · whisper-large-v3 en https://api.groq.com/openai/v1` |
| Directorios de escritura | OK | `logs, subidos e índice son escribibles` |
| Dataset | OK o AVISO | AVISO si no montó el dataset; no bloquea |

**LLM y STT son dos sondas separadas porque son dos servicios distintos**, con su
propia URL, su propia clave y su propio modelo. La del LLM no se conforma con
validar la clave: comprueba contra el proveedor que el modelo configurado
**existe**. El modo de falla que motivó esa sonda es «clave buena, modelo
apagado», que pasa toda verificación de credenciales y revienta en la primera
inferencia — ver [`docs/DECLARACION_MODELO.md`](docs/DECLARACION_MODELO.md).
Cada fila lleva el perfil y el proveedor en uso, para que se lean de un vistazo.

**«0 documentos» es correcto hoy**, no un error: el indexador del corpus aún no
existe, así que no hay semilla que sembrar y el índice arranca vacío.

Misma información en JSON, para automatizar:

```bash
curl -H "Accept: application/json" http://localhost:8080/salud
```

`/salud` responde **200 siempre**, también cuando el veredicto es NO LISTO. El
código HTTP dice «el proceso responde»; el veredicto dice «el sistema sirve».
Son dos cosas distintas, y por eso el `healthcheck` de Docker (`docker compose
ps` → `healthy`) **no** es la verificación: un contenedor puede estar `healthy`
y mudo. Mire la página.

---

## 4. Las claves

Las claves son lo único que este repositorio **no** trae. Son **dos**, porque
son dos servicios:

| Variable | Servicio | Proveedor |
|---|---|---|
| `LLM_API_KEY` | Modelo de lenguaje | El que sirva `LLM_MODELO`. Por defecto en `.env.example`: OpenRouter |
| `STT_API_KEY` | Transcripción de voz | Groq (`whisper-large-v3`) |

**Para la evaluación: las claves vienen en el informe final.** No están en el
repositorio ni lo estarán: una clave en git es una clave quemada.

### Por qué el LLM no es Groq

Porque Groq apagó los dos modelos de la lista permitida que servía: uno el
**24/01/2025** y el otro el **16/08/2026**. La solución conserva el
modelo exigido —Llama 3.1 70B— y lo pide a un proveedor que sí lo sirve. El
argumento completo, con fuentes y fechas de consulta, está en
**[`docs/DECLARACION_MODELO.md`](docs/DECLARACION_MODELO.md)**. El STT no está
afectado y sigue en Groq.

### Contingencia, fuera del cronómetro

Si una clave del informe no funciona o se agotó su cuota:

- **STT (Groq).** Entre a <https://console.groq.com>, regístrese, **API Keys** →
  **Create API Key**. La clave empieza por `gsk_` y **solo se muestra una vez**.
  Péguela en `STT_API_KEY=`, sin comillas y sin espacios alrededor del `=`. El
  plan gratuito basta para la demostración.
- **LLM.** Cree una clave en el proveedor que aparece en `.env.example` y
  péguela en `LLM_API_KEY=`. O evite el problema entero con el **fallback
  local**, que no necesita clave ni internet:

  ```bash
  docker compose --profile local up -d
  docker compose --profile local exec llm-local ollama pull llama3.2:3b
  ```

  y en `.env`: `LLM_BASE_URL=http://llm-local:11434/v1`, `LLM_MODELO=llama3.2:3b`,
  `LLM_PERFIL=local`, `LLM_API_KEY=` vacía.

Reinicie con `docker compose up -d` (con `sudo` en Linux) después de tocar `.env`.

### Leer el diagnóstico

| Lo que dice `/salud` | Qué pasó |
|---|---|
| `LLM_MODELO está vacío…` | No puso el identificador del modelo. El mensaje trae el valor exacto que va en cada perfil |
| `el proveedor rechaza la clave (HTTP 401)` | La clave llegó pero no es válida: sobra un espacio, falta un carácter, o está revocada |
| `el proveedor no sirve «…»; modelos disponibles que coinciden: …` | La clave está bien y el modelo no existe en ese proveedor. Copie uno de los que lista |
| `ausente` | El archivo `.env` no existe o la línea quedó vacía |

---

## 5. Operación

Comandos de uso diario. **Linux lleva `sudo`; macOS y Windows no.**

| Para | Linux | macOS / Windows |
|---|---|---|
| Ver estado del contenedor | `sudo docker compose ps` | `docker compose ps` |
| Ver logs en vivo | `sudo docker compose logs -f` | `docker compose logs -f` |
| Reiniciar | `sudo docker compose restart` | `docker compose restart` |
| Apagar (conserva el índice) | `sudo docker compose down` | `docker compose down` |
| Apagar y borrar todo | `sudo docker compose down -v` | `docker compose down -v` |

Los logs también quedan en texto plano en **`datos/logs/app.log`**, legibles con
cualquier editor y sin `docker cp`.

> En Linux con `sudo`, Docker crea `datos/` como propiedad de `root`. Para leer
> los logs sin `sudo`: `sudo chown -R "$USER" datos`.

`down -v` borra los volúmenes nombrados, **y con ellos el índice vectorial**.
`down` a secas lo conserva. En el estado actual da igual —el índice está
vacío—, pero dejará de darlo en cuanto exista el indexador.

---

## 6. Configuración

Todo entra por variable de entorno, y **todas las rutas son relativas a la raíz
del repositorio**. No hay ninguna ruta absoluta del host en el código, el
compose, el `.env.example` ni este documento; `scripts/sin_rutas_absolutas.sh`
lo verifica y falla si alguna se cuela.

`.env.example` documenta cada variable. Las que se tocan en la práctica:

| Variable | Default | Para qué |
|---|---|---|
| `LLM_BASE_URL` | *(vacía)* | Endpoint OpenAI-compatible del LLM. Obligatoria |
| `LLM_MODELO` | *(vacío)* | Identificador exacto del modelo. Obligatoria, **sin default a propósito** |
| `LLM_API_KEY` | *(vacía)* | Clave del proveedor del LLM. Obligatoria salvo en perfil local |
| `LLM_PERFIL` | `remoto` | `remoto` \| `local`. Informativo, lo muestra `/salud` |
| `STT_API_KEY` | *(vacía)* | Clave de Groq para la transcripción. Obligatoria |
| `PUERTO` | `8080` | Puerto del **host**. Cámbielo si 8080 está ocupado |
| `DATASET_DIR` | `./dataset` | Origen del bind del corpus (`:ro`) |
| `INDICE_BASE_DIR` | `./indice_base` | Origen de la semilla del índice (`:ro`) |
| `LOGS_HOST_DIR` | `./datos/logs` | Dónde quedan los logs en el host |
| `SALUD_COMPROBAR_RED` | `1` | `0` para no salir a la red al verificar la clave |

### Montajes, y por qué cada uno es como es

| Host | Contenedor | Modo | Razón |
|---|---|---|---|
| `./dataset` | `/app/dataset` | bind, `:ro` | Los PDFs son de terceros: viajan por git, no dentro de la imagen |
| `./indice_base` | `/opt/indice_base` | bind, `:ro` | Semilla del índice, misma razón |
| `datos_indice` | `/app/datos/indice` | **volumen nombrado**, rw | Ver abajo |
| `datos_subidos` | `/app/datos/subidos` | **volumen nombrado**, rw | Ídem |
| `./datos/logs` | `/app/datos/logs` | bind, rw | Texto plano; el operador tiene que poder leerlo sin `docker cp` |

**El índice va a volumen nombrado y no es negociable.** ChromaDB persiste sobre
SQLite. Un bind mount de Docker Desktop en macOS o Windows atraviesa una capa de
compartición de archivos cuya semántica de bloqueo **no reproduce la de POSIX**,
que es justo de lo que depende SQLite. El resultado no es un error claro: es
corrupción del índice o un cuelgue. Un volumen nombrado vive en el filesystem
nativo de la VM y no cruza esa capa.

Los binds llevan el sufijo `z` en `compose.yaml`. En Fedora, RHEL y derivados
—SELinux en enforcing— sin él el contenedor recibe `Permission denied` al leer
el dataset y al escribir los logs, aunque los permisos POSIX sean correctos. En
macOS y Windows el sufijo se ignora.

---

## 7. Qué hay dentro de la imagen

Los modelos están **vendorizados en tiempo de build**: el primer arranque no
descarga nada. Un modelo que se baja al arrancar es una dependencia de red en la
máquina del evaluador, en el peor momento posible.

- **Embedder:** `all-MiniLM-L6-v2` en ONNX, el que ChromaDB usa por defecto.
  384 dimensiones, CPU.
- **Voz:** Piper, `es_MX-ald-medium` (22 050 Hz).
- **Sin `torch`.** Todo corre sobre `onnxruntime`. Con torch la imagen pasaría
  de ~300 MB a varios GB.
- **Un solo proceso, un solo worker de uvicorn.** Dos workers serían dos
  procesos escribiendo el mismo SQLite sin coordinarse.
- **`kubernetes` se queda**, aunque `chromadb` solo lo use en su modo servidor
  sobre un clúster y aquí se use `PersistentClient` en proceso. Podarlo ahorraba
  **19,8 MB medidos** (300,2 MB con él, 280,4 MB sin él) sobre un presupuesto de
  400 MB donde ya sobran ~100, a
  cambio de un `ImportError` posible en cualquier ruta de `chromadb` que la
  prueba de humo del build no ejercita. La asimetría no cuadra. Además,
  desinstalar después de la auditoría de `requirements.txt` haría que ese
  archivo dejara de describir la imagen entregada, que es justo lo que la
  auditoría existe para impedir. La poda de `pip` y `setuptools` sí se conserva.

### Lo que NO está dentro de la imagen: LLM y STT

Son **servicios externos**, y por eso son las dos únicas cosas que piden clave:

| Servicio | Modelo | Dónde corre |
|---|---|---|
| Modelo de lenguaje | `meta-llama/llama-3.1-70b-instruct` (Llama 3.1 70B) | Proveedor remoto OpenAI-compatible |
| Transcripción (STT) | `whisper-large-v3` | Groq |

Los dos hablan el mismo protocolo OpenAI-compatible, así que son **una sola
integración con dos configuraciones**, no dos clientes. Esa es también la razón
de que el **fallback local** —Llama 3.2 sobre Ollama, celda «Local, CPU» de la
lista permitida— no sea código aparte: solo cambia `LLM_BASE_URL`.

```bash
docker compose --profile local up -d
docker compose --profile local exec llm-local ollama pull llama3.2:3b
```

El servicio `llm-local` de `compose.yaml` lleva `profiles: ["local"]`, así que
`docker compose up -d` a secas **no lo arranca** y la ruta principal no paga
nada por su existencia. Contra un `llama.cpp` u `ollama` que ya tenga corriendo
en su host, ni siquiera hace falta el perfil: apunte `LLM_BASE_URL` a
`http://host.docker.internal:11434/v1`.

Por qué el LLM no está en Groq, con fuentes y fechas:
**[`docs/DECLARACION_MODELO.md`](docs/DECLARACION_MODELO.md)**.

### Por qué esa voz

**No existe voz colombiana en Piper.** La elección real es entre español de
España y español latinoamericano, y es una decisión fonética, no estética:

- Las voces `es_ES` usan `espeak: es`, que **distingue /s/ de /θ/** — «sien» y
  «cien» suenan diferente. Esa distinción no existe en ningún dialecto
  colombiano; a un paciente le suena a locutor extranjero.
- Las voces `es_MX` usan `espeak: es-419` (español de América): **seseo y
  yeísmo**, que es lo que un hablante colombiano espera.

Entre las `es_MX`, se eligió `ald` en calidad `medium` (60 MB): equilibrio entre
peso e inteligibilidad. El mismo locutor tiene una variante `x_low` de 21 MB, así
que si hubiera que recortar la imagen se puede bajar de calidad **sin cambiarle
la voz al agente**. Cambiarla es tocar tres `ARG` en el `Dockerfile`.

Esto es una decisión de ingeniería sobre material disponible, no una validación
de aceptabilidad: **nadie ha probado esta voz con pacientes colombianos.**

---

## 8. Desarrollo

### Tests

La suite de `politica/` corre en el host, sin Docker:

```bash
pip install --user -r requirements-dev.txt
python3 -m pytest tests/ -v
```

Con el dataset presente se añade el criterio de aceptación sobre los 160 casos
del dev set; sin él ese test hace `skip` y el resto corre igual:

```bash
DATASET_DIR=./dataset python3 -m pytest tests/ -v
```

Detalle de qué cubre cada archivo: `tests/README.md`.

`requirements-dev.txt` (pytest, pandas, openpyxl) es **solo** para tests y no
entra en la imagen. `requirements.txt` es el runtime y sus versiones salen de un
`pip freeze` real; el build las vuelve a comparar y aborta si no coinciden.

### Compuerta de rutas absolutas

```bash
sh scripts/sin_rutas_absolutas.sh        # sale 0 si está limpio, 1 si no
sh scripts/sin_rutas_absolutas.sh -v     # además, cuántos archivos revisó
```

Busca los prefijos de directorio personal de Linux y de macOS, y la variable
`HOME` sin expandir, en los archivos del repositorio. Excluye `docs/bitacora.md`,
`docs/diseno/` y `scripts/verificacion_hd1_salida.txt` por ser **registro
fechado**: documentan qué se corrió y dónde, y editarlos a posteriori sería
falsear el registro. La deuda de la Fase 2.1 quedó saldada el 2026-08-09, así
que hoy la compuerta sale limpia, sin avisos.

### Estructura

```
app/            FastAPI: configuración y verificación de estado. Sin lógica clínica
politica/       Decisión clínica. stdlib pura, cerrado y verificado. NO se toca
tests/          Batería de politica/
scripts/        Oráculo de verificación y compuertas
docker/         entrypoint.sh: siembra del índice y arranque
dataset/        Corpus del reto (107 PDFs) y casos sintéticos. Viaja por git
docs/           bitacora.md (fuente de verdad del estado), DECLARACION_MODELO.md,
                diseño, procedencia
```

---

## 9. Métricas obligatorias

> **PENDIENTE DE MEDICIÓN.** Los encabezados están puestos; los números **no**
> se rellenan con estimaciones. Cada celda se llena con una corrida medida, y al
> lado va el comando o el procedimiento del que salió.

### 9.1 Levantamiento (G2)

| Métrica | Valor | Cómo se midió |
|---|---|---|
| Tiempo total de `clone` a veredicto LISTO | PENDIENTE DE MEDICIÓN | `docs/g2_cronometraje.md` |
| Tiempo de `docker compose pull` | PENDIENTE DE MEDICIÓN | |
| Tiempo de arranque hasta primera respuesta | PENDIENTE DE MEDICIÓN | |
| Nº de dudas del operador no resueltas por el README | PENDIENTE DE MEDICIÓN | |

### 9.2 Latencia del turno de voz

| Métrica | Valor | Cómo se midió |
|---|---|---|
| Latencia extremo a extremo por turno (p50) | PENDIENTE DE MEDICIÓN | |
| Latencia extremo a extremo por turno (p95) | PENDIENTE DE MEDICIÓN | |
| Latencia de STT | PENDIENTE DE MEDICIÓN | |
| Latencia del LLM | PENDIENTE DE MEDICIÓN | |
| Latencia de síntesis de voz | PENDIENTE DE MEDICIÓN | |

### 9.3 Calidad clínica

| Métrica | Valor | Cómo se midió |
|---|---|---|
| Recall de banderas rojas | PENDIENTE DE MEDICIÓN | |
| Falsos negativos críticos | PENDIENTE DE MEDICIÓN | |
| Tasa de escalamiento por nivel | PENDIENTE DE MEDICIÓN | |
| Turnos por conversación | PENDIENTE DE MEDICIÓN | |

### 9.4 Recuperación (RAG)

| Métrica | Valor | Cómo se midió |
|---|---|---|
| Documentos indexados | PENDIENTE DE MEDICIÓN | |
| Precisión de citas | PENDIENTE DE MEDICIÓN | |
| Tiempo de indexación del corpus | PENDIENTE DE MEDICIÓN | |

### 9.5 Empaquetado — medido

Únicos números ya medidos. Fecha: **2026-08-09**. Máquina: Fedora Linux
(x86_64), Docker 29.6.0.

| Métrica | Valor | Comando |
|---|---|---|
| Tamaño de la imagen, comprimida (lo que se descarga) | **300,2 MB** | `docker save ghcr.io/elorro/voice-agent-postop:v0.1.0 \| wc -c` → `300221440` |
| Tamaño de la imagen, en disco | 1,02 GB | `docker images ghcr.io/elorro/voice-agent-postop:v0.1.0` |
| Carga de embedder + voz, sin red | 2,4 s | `docker run --rm --network none …` (ver §10) |

Presupuesto: 400 MB comprimida. Holgura: **~100 MB**.

La medición anterior (2026-08-09, más temprano) daba **280,4 MB**. La diferencia
son los 19,8 MB de `kubernetes`, cuya desinstalación se revirtió el mismo día
(§7). El número vigente es el de arriba: describe la imagen que se entrega.

---

## 10. Si algo falla

| Síntoma | Causa | Solución |
|---|---|---|
| `docker: command not found` | Docker no instalado o Desktop apagado | Instálelo / ábralo y espere a que la ballena deje de moverse |
| `docker compose` → `is not a docker command` | Falta el plugin de Compose v2 | Linux: `sudo apt install docker-compose-plugin`. macOS/Windows: actualice Docker Desktop |
| `permission denied … docker daemon socket` | Linux sin `sudo` | Use `sudo` en **todos** los comandos |
| `port is already allocated` | Algo ocupa el 8080 | Ponga `PUERTO=8081` en `.env`, `up -d` otra vez, y abra `localhost:<PUERTO>` (8081 en este ejemplo), no 8080 |
| `/salud` no abre | El contenedor no arrancó | `docker compose ps` y `docker compose logs` |
| Veredicto NO LISTO, fila `LLM` o `STT` en rojo | Clave ausente, inválida, o modelo que el proveedor no sirve | §4 |
| `Permission denied` en dataset o logs (Fedora/RHEL) | SELinux sin la etiqueta `z` | Ya está en `compose.yaml`; si lo editó, no quite el `z` |
| `exec /usr/local/bin/entrypoint.sh: no such file` en Windows | El `.sh` se clonó con CRLF | `.gitattributes` lo evita. Si pasó: `git config core.autocrlf false`, borre la copia y vuelva a clonar |

Para comprobar que la imagen no necesita red después de instalada:

```bash
docker run --rm --network none ghcr.io/elorro/voice-agent-postop:v0.1.0 \
  python -c "from app.config import obtener_config; from app import salud; \
cfg=obtener_config(); print(salud.sondear_embedder(cfg).detalle, '|', salud.sondear_voz(cfg).detalle)"
```

---

## 11. Datos y límites

**Los datos clínicos de este proyecto son sintéticos y no están validados
clínicamente. Esto no es un dispositivo médico y no sustituye criterio
profesional.** Los PDFs del corpus conservan los derechos de sus autores y se
incluyen solo como material de referencia del reto.

Los 107 PDFs **viajan dentro del repositorio**, no en la imagen. Es deliberado:
la rúbrica exige trazabilidad, y una cita del RAG solo es verificable si el
evaluador puede abrir el documento citado.

Procedencia completa, licencias y qué no se puede concluir de las métricas:
**`docs/PROCEDENCIA_DATASET.md`**.

Modelo de lenguaje, compuerta G3 y fallback local:
**`docs/DECLARACION_MODELO.md`**.

Estado real del proyecto, decisiones y deuda técnica abierta:
**`docs/bitacora.md`**. Es la fuente de verdad; este README solo dice cómo se
levanta.
