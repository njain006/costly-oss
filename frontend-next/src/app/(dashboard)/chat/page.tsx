"use client";

import { useState, useRef, useEffect } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Bot, Send, User, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";

interface Message {
  role: "user" | "assistant";
  content: string;
  expert?: string | null;
  expert_name?: string | null;
}

const EXPERT_COLORS: Record<string, string> = {
  snowflake: "bg-sky-100 text-sky-700 border-sky-200",
  aws: "bg-orange-100 text-orange-700 border-orange-200",
  databricks: "bg-red-100 text-red-700 border-red-200",
  openai: "bg-emerald-100 text-emerald-700 border-emerald-200",
  anthropic: "bg-amber-100 text-amber-700 border-amber-200",
  dbt_cloud: "bg-orange-100 text-orange-700 border-orange-200",
  gemini: "bg-blue-100 text-blue-700 border-blue-200",
  gcp: "bg-blue-100 text-blue-700 border-blue-200",
};

const SUGGESTIONS = [
  "Why did our costs increase this month?",
  "Which warehouses should we downsize?",
  "What are our most expensive query patterns?",
  "Show me stale tables we can drop to save money",
  "Break down costs by user and team",
  "What quick wins can save us the most?",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const send = async (text?: string) => {
    const content = (text || input).trim();
    if (!content || loading) return;

    const userMsg: Message = { role: "user", content };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const res: { response: string; demo: boolean; expert?: string; expert_name?: string } = await api.post("/chat", {
        messages: newMessages,
      });
      setMessages([...newMessages, {
        role: "assistant",
        content: res.response,
        expert: res.expert,
        expert_name: res.expert_name,
      }]);
    } catch (err) {
      setMessages([
        ...newMessages,
        { role: "assistant", content: "Sorry, I encountered an error. Please try again." },
      ]);
    } finally {
      setLoading(false);
      textareaRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 flex items-center justify-center">
          <Sparkles className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">Costly AI</h1>
          <p className="text-sm text-slate-500">Ask anything about your data platform spend</p>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-4 pb-4">
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="h-16 w-16 rounded-2xl bg-gradient-to-br from-sky-500/10 to-blue-600/10 flex items-center justify-center mb-4">
              <Bot className="h-8 w-8 text-sky-500" />
            </div>
            <h2 className="text-lg font-semibold text-slate-700 mb-2">
              What would you like to know?
            </h2>
            <p className="text-sm text-slate-400 mb-6 max-w-md">
              I can analyze costs across all your connected platforms, find optimization opportunities, and answer questions about your data stack spending.
            </p>
            <div className="grid grid-cols-2 gap-2 max-w-lg">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="text-left text-sm px-3 py-2.5 rounded-lg border border-slate-200 text-slate-600 hover:border-sky-300 hover:text-sky-700 hover:bg-sky-50/50 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}>
            {msg.role === "assistant" && (
              <Avatar className="h-8 w-8 shrink-0 mt-1">
                <AvatarFallback className="bg-gradient-to-br from-sky-500 to-blue-600 text-white text-xs">
                  AI
                </AvatarFallback>
              </Avatar>
            )}
            <Card
              className={`max-w-[80%] px-4 py-3 ${
                msg.role === "user"
                  ? "bg-sky-600 text-white border-sky-600"
                  : "bg-white border-slate-200"
              }`}
            >
              {msg.role === "assistant" && msg.expert_name && (
                <Badge
                  variant="outline"
                  className={`text-[10px] font-medium mb-2 ${EXPERT_COLORS[msg.expert || ""] || "bg-slate-100 text-slate-600 border-slate-200"}`}
                >
                  {msg.expert_name}
                </Badge>
              )}
              <div
                className={`text-sm leading-relaxed ${
                  msg.role === "assistant" ? "text-slate-700 prose prose-sm prose-slate max-w-none" : "whitespace-pre-wrap"
                }`}
              >
                {msg.role === "assistant" ? (
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                ) : (
                  msg.content
                )}
              </div>
            </Card>
            {msg.role === "user" && (
              <Avatar className="h-8 w-8 shrink-0 mt-1">
                <AvatarFallback className="bg-slate-200 text-slate-600 text-xs">
                  <User className="h-4 w-4" />
                </AvatarFallback>
              </Avatar>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <Avatar className="h-8 w-8 shrink-0 mt-1">
              <AvatarFallback className="bg-gradient-to-br from-sky-500 to-blue-600 text-white text-xs">
                AI
              </AvatarFallback>
            </Avatar>
            <Card className="px-4 py-3 bg-white border-slate-200">
              <div className="flex items-center gap-2">
                <Skeleton className="h-3 w-3 rounded-full animate-pulse" />
                <span className="text-sm text-slate-400">Analyzing your data...</span>
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 pt-4">
        <div className="flex gap-2 items-end">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your data platform costs..."
            className="min-h-[44px] max-h-[120px] resize-none bg-white"
            rows={1}
          />
          <Button
            onClick={() => send()}
            disabled={!input.trim() || loading}
            size="icon"
            className="h-[44px] w-[44px] shrink-0 bg-sky-600 hover:bg-sky-700"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

