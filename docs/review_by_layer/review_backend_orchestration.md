# Backend / Orchestration — Review

---

## `backend/orchestration/llm_client.py`

**Error**: timed out

---

## `backend/orchestration/monthly_pipeline.py`

Line 23: `self.cfg = config or ConfigManager()`
- Violates: Secrets must come from environment variables or .env — never hardcoded in source

Line 42: `except Exception as exc:`
- Violates: Error handling: catch specific exceptions, never bare `except:` or `except Exception:` that silently swallows errors without logging

Line 54: `except Exception as exc:`
- Violates: Error handling: catch specific exceptions, never bare `except:` or `except Exception:` that silently swallows errors without logging

Line 72: `except Exception as exc:`
- Violates: Error handling: catch specific exceptions, never bare `except:` or `except Exception:` that silently swallows errors without logging

Line 83: `except Exception:`
- Violates: Error handling: catch specific exceptions, never bare `except:` or `except Exception:` that silently swallows errors without logging

Line 97: `logger.warning("ChromaDB seed failed (non-fatal): %s", exc)`
- Using `logger.warning` for a non-fatal error, but the error is not being re-raised or handled properly.
- Violates: Error handling: catch specific exceptions, never bare `except:` or `except Exception:` that silently swallows errors without logging

Line 100: `vector_db.store_block(...)`
- The `store_block` method is called without checking if the `vector_db` is initialized properly or if it's a valid instance.

> *Grounding dropped 6 unverifiable finding(s).*

---

## `backend/orchestration/weekly_pipeline.py`

**Error**: timed out

---

