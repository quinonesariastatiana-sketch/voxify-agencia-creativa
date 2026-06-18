# VoxifyHub Creative Director Agent — Setup

## 1. Instalar Python
Si no tienes Python: https://www.python.org/downloads/
Versión recomendada: 3.11+

## 2. Instalar dependencias
Abre PowerShell en la carpeta `voxify-agent` y ejecuta:
```
pip install -r requirements.txt
```

## 3. Configurar variables de entorno
Copia el archivo de ejemplo:
```
copy .env.example .env
```
Luego abre `.env` y completa:

### Claude API
- Ve a https://console.anthropic.com → API Keys → Create Key
- Pega la clave en `ANTHROPIC_API_KEY`

### Instagram + Facebook (Meta)
1. Ve a https://developers.facebook.com
2. Crea una app → tipo "Business"
3. Agrega productos: Instagram Graph API + Pages API
4. En tu app, ve a Graph API Explorer
5. Genera un token con permisos:
   - `instagram_basic`, `instagram_content_publish`
   - `pages_manage_posts`, `pages_read_engagement`
6. Convierte a token de larga duración (60 días):
   `GET /oauth/access_token?grant_type=fb_exchange_token&...`
7. Tu `INSTAGRAM_BUSINESS_ACCOUNT_ID`: en Instagram Business Suite → Configuración → ID de cuenta
8. Tu `FACEBOOK_PAGE_ID`: en la URL de tu página de Facebook

### LinkedIn
1. Ve a https://www.linkedin.com/developers/apps → Create App
2. Agrega producto: "Marketing Developer Platform"
3. En OAuth 2.0 → Request access tokens con scopes:
   - `w_organization_social`, `r_organization_social`
4. `LINKEDIN_ORGANIZATION_ID`: número en la URL de tu página de empresa

## 4. Ejecutar el agente

### Generar contenido semanal (modo recomendado para empezar)
```
python main.py --daily
```

### Publicar un post ahora
```
python main.py --post instagram "Los 3 errores que hacen que pierdas clientes" https://tu-imagen.com/img.jpg
python main.py --post facebook "Cómo la IA puede ayudar a tu restaurante"
python main.py --post linkedin "Por qué los negocios latinos necesitan automatización"
```

### Tarea libre al agente
```
python main.py --task "Crea un carrusel de Instagram sobre automatización de respuestas"
```

### Ver posts en el calendario
```
python main.py --list-posts
```

### Activar publicación automática (scheduler)
```
python main.py --schedule
```
El scheduler publica automáticamente según este horario (hora de Miami/ET):
- Instagram: Lun, Mié, Vie a las 9:00 AM
- Facebook: Mar, Jue a las 10:00 AM
- LinkedIn: Lun, Mié a las 8:00 AM

### Modo interactivo (chat)
```
python main.py
```

## Notas importantes
- El agente usa Claude Opus 4.8 con pensamiento adaptativo — las respuestas pueden tardar 30-90 segundos
- Instagram **requiere imagen** para publicar. Sin URL de imagen, el post se omite
- Los tokens de Meta expiran cada 60 días; deberás renovarlos manualmente
- Toda la actividad queda registrada en `voxify.db` (SQLite)
