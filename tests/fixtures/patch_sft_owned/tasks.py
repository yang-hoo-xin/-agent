"""Independently authored repair demonstrations; never AccurateCrosshair code.

C2 is explicitly authorized teacher supervision. Family splits are fixed before
training; related variants stay in the same split. Hidden checks use real CLR
execution, values and files, never source-substring assertions.
"""
from __future__ import annotations

USINGS = "using System;\nusing System.IO;\nusing System.Linq;\nusing System.Collections.Generic;\n"


def subject(members, signature, body):
    return USINGS + "public sealed class Subject\n{\n" + members + "\n    public " + signature + "\n    {\n" + body + "\n    }\n}\n"


def task(case, family, split, request, members, signature, bodies, checks):
    return {"case_id": case, "family_id": family, "split": split, "request": request,
            "target_symbol": "Apply", "sources": {version: subject(members, signature, body)
                for version, body in zip(("B0", "C1", "C2"), bodies, strict=True)}, "checks": checks}


TASKS = [
task("samples_without_publication", "shared_state_optional_effect", "train",
 "Honor the publish option. Every accepted sample must still update Count, Total and Last when publishing is disabled. Enabled publishing and accumulated values retain their original behavior.",
 "    public int Count, Total, Last, Published;", "void Apply(int sample, bool publish)",
 ("        Count++; Total += sample; Last = sample; Published++;",
  "        if (!publish) return;\n        Count++; Total += sample; Last = sample; Published++;",
  "        Count++; Total += sample; Last = sample;\n        if (publish) Published++;"),
 'var s=new Subject(); s.Apply(7,false); Check("off_state",new[]{s.Count,s.Total,s.Last},new[]{1,7,7}); Check("off_effect",s.Published,0); s.Apply(3,true); Check("mixed_state",new[]{s.Count,s.Total,s.Last,s.Published},new[]{2,10,3,1}); var p=new Subject();p.Apply(4,true);Check("enabled_original",new[]{p.Count,p.Total,p.Last,p.Published},new[]{1,4,4,1},"preservation");'),
task("alarm_without_logging", "shared_state_optional_effect", "train",
 "Honor logEnabled without disabling initialization, last-value tracking or the safety alarm for values above 10. Logging remains one write per enabled call, and alarms accumulate across calls.",
 "    public bool Initialized; public int Last, Alarms, LogWrites;", "void Apply(int value, bool logEnabled)",
 ("        Initialized=true; Last=value; if(value>10) Alarms++; LogWrites++;",
  "        if(!logEnabled) return;\n        Initialized=true; Last=value; if(value>10) Alarms++; LogWrites++;",
  "        Initialized=true; Last=value; if(value>10) Alarms++;\n        if(logEnabled) LogWrites++;"),
 'var s=new Subject();s.Apply(15,false);Check("off_init",s.Initialized,true);Check("off_alarm",new[]{s.Last,s.Alarms,s.LogWrites},new[]{15,1,0});s.Apply(3,true);Check("mixed",new[]{s.Last,s.Alarms,s.LogWrites},new[]{3,1,1});var p=new Subject();p.Apply(20,true);Check("enabled_original",new[]{p.Last,p.Alarms,p.LogWrites},new[]{20,1,1},"preservation");'),
task("reservation_is_atomic", "validation_before_mutation", "train",
 "Return false for nonpositive quantities or quantities above remaining inventory, without changing Available or Audit. Successful reservations decrease Available and increment Audit once; subsequent requests use remaining inventory.",
 "    public int Available=8, Audit;", "bool Apply(int quantity)",
 ("        Available-=quantity; Audit++; return true;",
  "        Available-=quantity;\n        if(quantity<=0 || quantity>8) return false;\n        Audit++; return true;",
  "        if(quantity<=0 || quantity>Available) return false;\n        Available-=quantity; Audit++; return true;"),
 'var a=new Subject();Check("negative_rejected",a.Apply(-2),false);Check("negative_atomic",new[]{a.Available,a.Audit},new[]{8,0});var b=new Subject();Check("too_many_rejected",b.Apply(9),false);Check("too_many_atomic",new[]{b.Available,b.Audit},new[]{8,0});var c=new Subject();Check("valid",c.Apply(6),true,"preservation");Check("valid_state",new[]{c.Available,c.Audit},new[]{2,1},"preservation");Check("remaining_limit",c.Apply(3),false);Check("remaining_atomic",new[]{c.Available,c.Audit},new[]{2,1});'),
task("transfer_is_atomic", "validation_before_mutation", "train",
 "Reject nonpositive transfers and insufficient source balance before modifying either account or Transfers. Support transfers in both directions and preserve successful transfer amounts.",
 "    public int Left=9, Right=2, Transfers;", "bool Apply(int amount, bool toRight)",
 ("        if(toRight){Left-=amount;Right+=amount;}else{Right-=amount;Left+=amount;} Transfers++; return true;",
  "        if(toRight){Left-=amount;Right+=amount;}else{Right-=amount;Left+=amount;}\n        if(amount<=0 || Left<0 || Right<0) return false;\n        Transfers++; return true;",
  "        if(amount<=0 || amount>(toRight?Left:Right)) return false;\n        if(toRight){Left-=amount;Right+=amount;}else{Right-=amount;Left+=amount;} Transfers++; return true;"),
 'var s=new Subject();Check("insufficient",s.Apply(3,false),false);Check("rejected_state",new[]{s.Left,s.Right,s.Transfers},new[]{9,2,0});Check("negative",s.Apply(-1,true),false);Check("negative_state",new[]{s.Left,s.Right,s.Transfers},new[]{9,2,0});var p=new Subject();Check("forward",p.Apply(4,true),true,"preservation");Check("reverse",p.Apply(3,false),true,"preservation");Check("success_state",new[]{p.Left,p.Right,p.Transfers},new[]{8,3,2},"preservation");'),
task("cancel_exact_pending_id", "queue_cancellation", "train",
 "Cancel all queued occurrences of the selected ID, returning the number removed. Preserve every other pending ID in FIFO order. Unknown IDs and an empty queue must remain harmless.",
 "    public Queue<string> Pending=new Queue<string>();", "int Apply(string id)",
 ("        return 0;",
  "        int found=Pending.Count(x=>x==id);\n        if(found>0) Pending.Clear();\n        return found;",
  "        int removed=0, count=Pending.Count;\n        for(int i=0;i<count;i++){string item=Pending.Dequeue();if(item==id)removed++;else Pending.Enqueue(item);}\n        return removed;"),
 'var s=new Subject();foreach(var x in new[]{"a","b","a","c"})s.Pending.Enqueue(x);Check("removed",s.Apply("a"),2);Check("survivor_order",s.Pending.ToArray(),new[]{"b","c"});var p=new Subject();p.Pending.Enqueue("x");p.Pending.Enqueue("y");Check("missing_count",p.Apply("z"),0,"preservation");Check("missing_order",p.Pending.ToArray(),new[]{"x","y"},"preservation");Check("empty",new Subject().Apply("a"),0,"preservation");'),
task("cancel_pending_group", "queue_cancellation", "train",
 "Cancel queued entries whose group before ':' exactly equals the requested group. Return the count, inspect the entire queue even if its head belongs to another group, and preserve survivor order and the distinction between group 'a' and 'ab'.",
 "    public Queue<string> Pending=new Queue<string>();", "int Apply(string group)",
 ("        return 0;",
  "        int removed=0;\n        while(Pending.Count>0 && Pending.Peek().Split(':')[0]==group){Pending.Dequeue();removed++;}\n        return removed;",
  "        int removed=0,count=Pending.Count;\n        for(int i=0;i<count;i++){var item=Pending.Dequeue();if(item.Split(':')[0]==group)removed++;else Pending.Enqueue(item);}\n        return removed;"),
 'var s=new Subject();foreach(var x in new[]{"b:0","a:1","ab:2","a:3","c:4"})s.Pending.Enqueue(x);Check("whole_queue",s.Apply("a"),2);Check("exact_group_order",s.Pending.ToArray(),new[]{"b:0","ab:2","c:4"});var p=new Subject();p.Pending.Enqueue("x:0");Check("unknown",p.Apply("z"),0,"preservation");Check("unknown_preserved",p.Pending.ToArray(),new[]{"x:0"},"preservation");'),
task("snapshot_nested_tags", "snapshot_aliasing", "validation",
 "Return an independent copy of the records and their nested tag lists. Mutating either the returned record tags or a later live tag must not affect the other snapshot. Preserve record order and all existing tag values.",
 "    public List<List<string>> Records=new List<List<string>>{new List<string>{\"red\"},new List<string>{\"blue\"}};", "List<List<string>> Apply()",
 ("        return Records;",
  "        return new List<List<string>>(Records);",
  "        return Records.Select(tags=>new List<string>(tags)).ToList();"),
'''var s=new Subject();
var initial=new { Records=s.Records.Select(x=>x.ToArray()).ToArray() };
var steps=new List<object>();
var snap=s.Apply();
steps.Add(new { step=1, action="call", target="live", member="Apply" });
Check("original_values",snap.Select(x=>x.ToArray()).ToArray(),new[]{new[]{"red"},new[]{"blue"}},"preservation",
    TraceInput(initial,steps,new { target="snapshot" }));
snap[0].Add("changed");
steps.Add(new { step=2, action="add", target="snapshot", record_index=0, value="changed" });
Check("snapshot_not_live",s.Records[0].ToArray(),new[]{"red"},input:
    TraceInput(initial,steps,new { target="live", member="Records", record_index=0 }));
s.Records[1].Add("later");
steps.Add(new { step=3, action="add", target="live", member="Records", record_index=1, value="later" });
Check("live_not_snapshot",snap[1].ToArray(),new[]{"blue"},input:
    TraceInput(initial,steps,new { target="snapshot", record_index=1 }));
snap.Add(new List<string>{"third"});
steps.Add(new { step=4, action="add_record", target="snapshot", values=new[]{"third"} });
Check("outer_independent",s.Records.Count,2,input:
    TraceInput(initial,steps,new { target="live", member="Records.Count" }));'''),
task("snapshot_nested_properties", "snapshot_aliasing", "validation",
 "Return an independent map of per-user property maps. Both inner updates and new outer entries must stay isolated in either direction. Preserve original property values and names.",
 "    public Dictionary<string,Dictionary<string,int>> Users=new Dictionary<string,Dictionary<string,int>>{{\"u\",new Dictionary<string,int>{{\"score\",4}}}};", "Dictionary<string,Dictionary<string,int>> Apply()",
 ("        return Users;",
  "        return new Dictionary<string,Dictionary<string,int>>(Users);",
  "        return Users.ToDictionary(pair=>pair.Key,pair=>new Dictionary<string,int>(pair.Value));"),
 'var s=new Subject();var snap=s.Apply();Check("original_score",snap["u"]["score"],4,"preservation");snap["u"]["score"]=9;Check("inner_not_live",s.Users["u"]["score"],4);s.Users["u"]["later"]=1;Check("live_not_inner",snap["u"].ContainsKey("later"),false);snap["v"]=new Dictionary<string,int>();Check("outer_not_live",s.Users.ContainsKey("v"),false);'),
task("paging_partial_tail", "pagination_boundary", "holdout",
 "Add advancing page reads: Apply returns the next page, including a final partial page, and advances Offset only by returned items. Once exhausted, return empty without changing Offset. Preserve item ordering and full-sized first pages.",
 "    public int[] Items={10,20,30,40,50}; public int Offset;", "int[] Apply(int size)",
 ("        return Items.Take(size).ToArray();",
  "        if(Offset+size>Items.Length){Offset=Items.Length;return Array.Empty<int>();}\n        var page=Items.Skip(Offset).Take(size).ToArray();Offset+=size;return page;",
  "        var page=Items.Skip(Offset).Take(size).ToArray();Offset+=page.Length;return page;"),
'''var s=new Subject();
var initial=new { Items=s.Items.ToArray(), Offset=s.Offset };
var steps=new List<object>();
var size=2;
var offsetBefore=s.Offset;
var page=s.Apply(size);
steps.Add(new { step=1, action="call", target="s", member="Apply", arguments=new { size }, offset_before=offsetBefore, offset_after=s.Offset });
Check("first_full",page,new[]{10,20},"preservation",TraceInput(initial,steps,new { target="return_value", step=1 }));
offsetBefore=s.Offset;
page=s.Apply(size);
steps.Add(new { step=2, action="call", target="s", member="Apply", arguments=new { size }, offset_before=offsetBefore, offset_after=s.Offset });
Check("second_full",page,new[]{30,40},input:TraceInput(initial,steps,new { target="return_value", step=2 }));
offsetBefore=s.Offset;
page=s.Apply(size);
steps.Add(new { step=3, action="call", target="s", member="Apply", arguments=new { size }, offset_before=offsetBefore, offset_after=s.Offset });
Check("tail",page,new[]{50},input:TraceInput(initial,steps,new { target="return_value", step=3 }));
Check("exact_offset",s.Offset,5,input:TraceInput(initial,steps,new { target="s", member="Offset" }));
offsetBefore=s.Offset;
page=s.Apply(size);
steps.Add(new { step=4, action="call", target="s", member="Apply", arguments=new { size }, offset_before=offsetBefore, offset_after=s.Offset });
Check("exhausted",page,Array.Empty<int>(),input:TraceInput(initial,steps,new { target="return_value", step=4 }));
Check("stable_offset",s.Offset,5,input:TraceInput(initial,steps,new { target="s", member="Offset" }));
var p=new Subject();
var otherInitial=new { Items=p.Items.ToArray(), Offset=p.Offset };
var otherSteps=new List<object>();
var largeSize=8;
var otherOffsetBefore=p.Offset;
var largePage=p.Apply(largeSize);
otherSteps.Add(new { step=1, action="call", target="p", member="Apply", arguments=new { size=largeSize }, offset_before=otherOffsetBefore, offset_after=p.Offset });
Check("large_page",largePage,new[]{10,20,30,40,50},input:TraceInput(otherInitial,otherSteps,new { target="return_value", step=1 }));'''),
task("paging_resume_cursor", "pagination_boundary", "holdout",
 "Add a continuation cursor: a page begins at Cursor, which always names the next unread item. A nonzero resume cursor must neither repeat nor skip an item. Exhaustion retains the end cursor and returns empty; order remains unchanged.",
 "    public string[] Items={\"a\",\"b\",\"c\",\"d\"}; public int Cursor;", "string[] Apply(int size)",
 ("        return Items.Skip(Cursor).Take(size).ToArray();",
  "        var page=Items.Skip(Cursor).Take(size).ToArray();\n        if(page.Length>0)Cursor+=page.Length-1;return page;",
  "        var page=Items.Skip(Cursor).Take(size).ToArray();Cursor+=page.Length;return page;"),
 'var s=new Subject{Cursor=1};Check("resume_first",s.Apply(2),new[]{"b","c"},"preservation");Check("next_cursor",s.Cursor,3);Check("resume_tail",s.Apply(2),new[]{"d"});Check("end_cursor",s.Cursor,4);Check("end_empty",s.Apply(2),Array.Empty<string>());Check("end_stable",s.Cursor,4);'),
task("commit_partial_write_failure", "durable_commit_failure", "holdout",
 "Commit pending lines transactionally. If writing the second pending line raises the injected IOException, the previous committed file bytes and the pending list must remain unchanged. Success replaces the file with pending lines and clears Pending. Temporary partial output must not be mistaken for committed content.",
 "    public List<string> Pending=new List<string>(); public bool FailWrite;", "void Apply(string path)",
 ("        File.WriteAllLines(path,Pending); Pending.Clear();",
  "        using(var writer=new StreamWriter(path)){for(int i=0;i<Pending.Count;i++){if(FailWrite && i==1)throw new IOException(\"injected\");writer.WriteLine(Pending[i]);}}Pending.Clear();",
  "        string temp=path+\".pending\";\n        try{using(var writer=new StreamWriter(temp)){for(int i=0;i<Pending.Count;i++){if(FailWrite && i==1)throw new IOException(\"injected\");writer.WriteLine(Pending[i]);}}File.Move(temp,path,true);Pending.Clear();}\n        finally{if(File.Exists(temp))File.Delete(temp);}"),
 r'string path=Path.Combine(root,"committed.txt");File.WriteAllText(path,"old\n");var s=new Subject{FailWrite=true};s.Pending.AddRange(new[]{"new1","new2"});bool failed=false;try{s.Apply(path);}catch(IOException){failed=true;}Check("failure_observed",failed,true);Check("old_file_retained",File.ReadAllText(path),"old\n");Check("pending_retained",s.Pending.ToArray(),new[]{"new1","new2"});var p=new Subject();p.Pending.AddRange(new[]{"a","b"});p.Apply(path);Check("successful_file",File.ReadAllLines(path),new[]{"a","b"},"preservation");Check("successful_clear",p.Pending.Count,0,"preservation");'),
task("commit_replace_failure", "durable_commit_failure", "holdout",
 "Advance the committed version only after replacement succeeds. An injected failure at replacement must leave previous file bytes, Version and Pending unchanged. A later successful commit must publish all pending lines, increment Version exactly once, and clear Pending.",
 "    public List<string> Pending=new List<string>(); public int Version=3; public bool FailReplace;", "void Apply(string path)",
 ("        File.WriteAllLines(path,Pending);Version++;Pending.Clear();",
  "        File.WriteAllLines(path,Pending);Version++;Pending.Clear();\n        if(FailReplace)throw new IOException(\"replace unavailable\");",
  "        string temp=path+\".pending\";\n        try{File.WriteAllLines(temp,Pending);if(FailReplace)throw new IOException(\"replace unavailable\");File.Move(temp,path,true);Version++;Pending.Clear();}\n        finally{if(File.Exists(temp))File.Delete(temp);}"),
 r'string path=Path.Combine(root,"version.txt");File.WriteAllText(path,"previous\n");var s=new Subject{FailReplace=true};s.Pending.Add("next");bool failed=false;try{s.Apply(path);}catch(IOException){failed=true;}Check("replacement_failed",failed,true);Check("prior_file",File.ReadAllText(path),"previous\n");Check("prior_version",s.Version,3);Check("pending_survives",s.Pending.ToArray(),new[]{"next"});var p=new Subject();p.Pending.Add("ok");p.Apply(path);Check("success_file",File.ReadAllLines(path),new[]{"ok"},"preservation");Check("success_state",new[]{p.Version,p.Pending.Count},new[]{4,0},"preservation");'),
]


def harness(checks):
    return USINGS + '''using System.Text.Json;
public static class Program
{
    static List<Dictionary<string,object>> Rows=new List<Dictionary<string,object>>();
    static object TraceInput(object initialState,object operations,object observation)
    {
        return JsonSerializer.Deserialize<JsonElement>(JsonSerializer.Serialize(new {
            initial_state=initialState, operations, observation }));
    }
    static void Check(string name,object actual,object expected,string group="new",object input=null)
    {
        var row=new Dictionary<string,object>{{"check",name},{"observed",actual},{"expected",expected},
            {"group",group},{"passed",JsonSerializer.Serialize(actual)==JsonSerializer.Serialize(expected)}};
        if(input!=null)row.Add("input",input);
        Rows.Add(row);
    }
    public static int Main(string[] args)
    {
        string root=args[0];Directory.CreateDirectory(root);
        try {
''' + checks + '''
        } catch(Exception error){Check("unexpected_exception",error.GetType().Name,"none");}
        Console.WriteLine(JsonSerializer.Serialize(Rows));
        return Rows.All(row=>(bool)row["passed"])?0:1;
    }
}
'''
