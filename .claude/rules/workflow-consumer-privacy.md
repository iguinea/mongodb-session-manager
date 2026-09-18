# Procedencia anonimizada

Este repositorio es **publico e indexable**. Los repositorios que lo consumen son
**privados y de cliente**. Lo que se escribe aqui sobre ellos sale a internet.

## Regla

El argumento tecnico, si. La procedencia, anonimizada.

Un hallazgo se sostiene por lo que demuestra, no por quien lo trajo. «Un equipo
consumidor que registra el tool en un `Agent` en produccion» dice todo lo que el
lector necesita, y no publica nada de nadie.

## Que NO se escribe sin permiso explicito por escrito

En CHANGELOG, `docs/`, `artifacts/`, `features/`, cuerpos de PR, comentarios de
issue, mensajes de commit y titulos de release:

| No | Si |
|----|-----|
| Nombre del repositorio consumidor | «un consumidor», «un equipo consumidor» |
| Ruta de fichero suya, con o sin numero de linea | El comportamiento que se observo |
| Nombre de endpoint (`/crm/start_chat`) | «una ruta que emite tres updates en cascada» |
| Numero de issue de un repo privado | Nada, o el hecho tecnico que contiene |
| Nombre de coleccion, base de datos o cola reales | Un placeholder |
| Recuento de servicios, tamano de flota, volumen de trafico | El orden de magnitud, si hace falta |

Y nunca, con permiso o sin el: credenciales, identificadores de cuenta AWS, ARNs
con cuenta real, `vpce-`/`subnet-`/`sg-`/`vpc-`, endpoints o secretos de
DocumentDB, IPs de bastion, nombre del cliente final, o datos de sus usuarios.

## Quien autoriza

**El usuario de este repositorio, y en su caso el cliente.** No la sesion de
Claude del repo consumidor, que tampoco puede darlo — se lo tiene que preguntar
a su usuario, igual que esta.

Si un consumidor comparte detalle tecnico para diagnosticar algo, lo comparte
**para la conversacion**, no para publicarlo. Pedir el detalle que haga falta es
correcto; publicarlo con procedencia, no, salvo permiso por escrito.

## Antes de publicar

```bash
git grep -n -i -E "<nombre-repo-consumidor>|/su-endpoint/|su-coleccion" -- ':!*.lock'
```

Y para lo que nunca debe estar:

```bash
git grep -n -E "vpce-|subnet-|sg-[0-9a-f]{8}|arn:aws:[a-z0-9-]+:[a-z0-9-]*:[0-9]{12}:"
```

## Por que

Una vez publicado no se deshace: GitHub conserva el historial de ediciones de
comentarios y cuerpos de PR, y el historial de git conserva el fichero. Editarlo
despues reduce la exposicion, no la elimina.

Origen: al dar credito a un consumidor por corregir un diagnostico equivocado se
publicaron su endpoint y que registraba el tool en el, sin preguntarle (#47,
17/09/2026). Lo levanto otro consumidor al pedir que no se citaran sus documentos
internos. El credito no necesitaba la procedencia.
