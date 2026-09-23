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


# Optional parameters whose values live in the schema, the way FastAPI and any OpenAPI 3.1 document carry them.
PARAMETERS = """
openapi: 3.1.0
info: {title: Parameters, version: "1"}
components:
  schemas:
    Limit: {type: integer, examples: [10], default: 20}
paths:
  /items:
    get:
      operationId: listItems
      parameters:
        - {name: author, in: query, schema: {type: integer, examples: [1]}}
        - {name: limit, in: query, schema: {$ref: "#/components/schemas/Limit"}}
        - {name: page, in: query, schema: {type: integer, default: 3}}
        - {name: sort, in: query, schema: {type: string}}
        - {name: q, in: query, example: given, schema: {type: string, examples: [from the schema]}}
        - {name: X-Mode, in: header, schema: {type: string, const: fast}}
      responses:
        "200": {description: ok}
"""


# Scalars YAML would type on its own: an unquoted timestamp example, a date enum, an on/off enum.
YAML_SCALARS = """
openapi: 3.0.3
info: {title: Scalars, version: "1"}
components:
  schemas:
    Day: {type: string, enum: [2024-01-31, 2024-02-29]}
    Switch: {type: string, enum: [on, off]}
    Report:
      type: object
      required: [day, switch]
      properties:
        day: {$ref: "#/components/schemas/Day"}
        switch: {$ref: "#/components/schemas/Switch"}
paths:
  /reports:
    get:
      operationId: listReports
      parameters:
        - name: since
          in: query
          required: true
          schema: {type: string, format: date-time}
          example: 2024-01-31T12:00:00Z
      responses:
        "200": {description: ok, content: {application/json: {schema: {$ref: "#/components/schemas/Report"}}}}
"""
