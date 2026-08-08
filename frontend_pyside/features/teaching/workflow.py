from datetime import datetime
class TeachingWorkflow:
    def __init__(self,adapter): self.adapter=adapter; self.sessions={}
    def session(self,module): return self.sessions.setdefault(module,{"records":[],"prediction_correct":False,"diagnostic":{},"conclusion":""})
    def evaluate(self,module,inputs): return self.adapter.evaluate(module,inputs)
    def record(self,module,inputs,result,note=""):
        rec={"time":datetime.now().strftime("%H:%M:%S"),"inputs":dict(inputs),"metrics":dict(result.get("metrics",{})),"note":note}; self.session(module)["records"].append(rec); return rec
    def prediction(self,module,answer):
        out=self.adapter.prediction(module,{"answer":answer}); self.session(module)["prediction_correct"]=out["correct"]; return out
    def scan(self,module,inputs,parameter,metric,start,stop,points): return self.adapter.scan(module,{"inputs":inputs,"parameter":parameter,"metric":metric,"start":start,"stop":stop,"points":points})
    def diagnostics(self,module,inputs,grid_points=65,window_factor=3.0):
        out=self.adapter.diagnostics(module,{"inputs":inputs,"settings":{"grid_points":grid_points,"window_factor":window_factor}}); self.session(module)["diagnostic"]=out; return out
    def score(self,module,result,conclusion):
        s=self.session(module); s["conclusion"]=conclusion; payload={**s,"task_passed":result.get("task_status",{}).get("passed",False)}; out=self.adapter.score(module,payload); s['score']=out; return out
    def report(self,module,inputs,result,conclusion):
        s=self.session(module); payload={**s,"inputs":inputs,"task_passed":result.get("task_status",{}).get("passed",False),"conclusion":conclusion}; return self.adapter.report(module,payload)
