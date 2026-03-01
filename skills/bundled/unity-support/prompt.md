# Unity/C# Development Context

## Project Structure
- All game code is in `Assets/Scripts/` (or `Assets/<feature>/`)
- Prefabs in `Assets/Prefabs/`, scenes in `Assets/Scenes/`
- Each MonoBehaviour script must match its filename exactly

## C# Coding Standards
- Use `[SerializeField] private` instead of `public` for Inspector-exposed fields
- Prefer `TryGetComponent<T>` over `GetComponent<T>` when component may not exist
- Cache component references in `Awake()` — never call `GetComponent` in `Update()`
- Use `CompareTag()` instead of string equality for tag checks
- Avoid `Find()` and `FindObjectOfType()` at runtime — use dependency injection or events

## Common Pitfalls
- Destroying objects: always use `Destroy(gameObject)`, never `Object.DestroyImmediate` at runtime
- NullReferenceException: always null-check before accessing optional components
- Coroutines: `StartCoroutine()` returns a `Coroutine` — stop them with `StopCoroutine()` to prevent leaks
- Physics: use `FixedUpdate()` for Rigidbody operations, not `Update()`

## Performance
- Pool frequently instantiated/destroyed objects (bullets, particles)
- Use `WaitForSeconds` cache instead of `new WaitForSeconds` in coroutines
- Prefer events/delegates over polling in `Update()`
