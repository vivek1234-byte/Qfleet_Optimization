"""
Authentication: password hashing, session tokens, and the sign-in routes.

Split so the pieces can be reasoned about separately:

* ``security`` — bcrypt and JWT. No FastAPI, no database.
* ``schemas`` — request and response shapes. Responses list their fields
  explicitly, which is what keeps ``password_hash`` out of the API.
* ``service`` — the database operations behind sign-in and employee
  administration, shared by both routers.
* ``deps`` — FastAPI dependencies that turn a bearer token into an
  ``Employee`` and enforce roles.
* ``api`` — ``/api/auth/*``
"""
