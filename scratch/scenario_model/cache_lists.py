"""Construit les 54 listes une fois et les met en cache (pickle) pour itérer sur le modèle de scénario."""
import pickle, sys
from aospy.l3 import scenario_model as sm
pool, lists = sm.build_pool()
sys.setrecursionlimit(20000)
pickle.dump(lists, open("scratch/output/scenario_lists.pkl", "wb"))
print(len(lists))
