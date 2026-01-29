import sys, traceback
print("sys.path[0] =", sys.path[0])

try:
    import app.loader as L
    print("\nImported app.loader OK\n")
    print("Has load_llm:", hasattr(L, "load_llm"))
    print("Has load_tools:", hasattr(L, "load_tools"))
    print("Has load_agents:", hasattr(L, "load_agents"))
    print("Has load_tasks:", hasattr(L, "load_tasks"))
    print("Has load_crew:", hasattr(L, "load_crew"))
except Exception as e:
    print("\nFAILED importing app.loader:")
    traceback.print_exc()