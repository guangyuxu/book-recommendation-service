"""HTTP routers for the BFF: the chat proxy (streaming turns + HITL).

Auth (signup/login) and family/child CRUD moved to the accounts service; the BFF only verifies
tokens and proxies chat.
"""
