# Task: add RequireComponent attributes for PlayerController's hard dependencies

`PlayerController` calls `GetComponent<T>()` in `Awake` for components it
needs. Add `[RequireComponent(typeof(T))]` attributes on the class for
every component PlayerController relies on via GetComponent.
