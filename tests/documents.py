"""Documents the generator's tests share: small, and covering every branch the renderer has."""

BOOKISH = """
openapi: 3.0.3
info: {title: Bookish, version: "1.2"}
servers: [{url: https://api.example.com/v1}]
security: [{bearer: []}]
components:
  securitySchemes:
    bearer: {type: http, scheme: bearer}
  schemas:
    Thing:
      type: object
      required: [name, size]
      additionalProperties: false
      properties:
        id: {type: integer}
        name: {type: string, example: x}
        size: {type: integer}
    ThingList: {type: array, items: {$ref: "#/components/schemas/Thing"}}
paths:
  /things:
    get:
      operationId: listThings
      tags: [things]
      summary: List things
      parameters:
        - {name: limit, in: query, required: false, schema: {type: integer}, example: 10}
      responses:
        "200": {description: ok, content: {application/json: {schema: {$ref: "#/components/schemas/ThingList"}}}}
  /owners/{owner}/things:
    post:
      operationId: createThing
      tags: [things]
      summary: Create a thing
      parameters:
        - {name: owner, in: path, required: true, schema: {type: integer}, example: 7}
        - {name: X-Trace, in: header, required: false, schema: {type: string}, example: abc}
      requestBody:
        required: true
        content: {application/json: {schema: {$ref: "#/components/schemas/Thing"}}}
      responses:
        "201": {description: made, content: {application/json: {schema: {$ref: "#/components/schemas/Thing"}}}}
  /ping:
    get:
      operationId: ping
      security: []
      responses:
        "200": {description: pong, content: {text/plain: {schema: {type: string}}}}
    post:
      operationId: echo
      security: []
      requestBody:
        required: true
        content: {text/plain: {schema: {type: string}, example: hello}}
      responses:
        "200": {description: echoed}
  /upload:
    post:
      operationId: upload
      tags: [files]
      security: []
      requestBody:
        required: true
        content: {application/octet-stream: {schema: {type: string, format: binary}}}
      responses:
        "200": {description: stored}
  /search:
    get:
      operationId: search
      tags: [things]
      security: []
      parameters:
        - {name: q, in: query, required: true, schema: {type: string}}
        - {name: page-size, in: query, required: false, schema: {type: integer}, example: 5}
      responses:
        "200": {description: hits}
"""

NO_SCHEMAS = """
openapi: 3.1.0
info: {title: Bare, version: "0"}
paths:
  /health:
    get:
      responses:
        "204": {description: fine}
"""
