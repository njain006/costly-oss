"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { GoogleLogin } from "@react-oauth/google";
import { useAuth } from "@/providers/auth-provider";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DollarSign, Loader2, ArrowLeft, BarChart3, Bot, Sparkles } from "lucide-react";

interface AuthResponse {
  token: string;
  refresh_token: string;
  user_id: string;
  name: string;
  email: string;
  role?: string;
}

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Sign In state
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  // Register state
  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");

  // Forgot password
  const [showForgot, setShowForgot] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotSent, setForgotSent] = useState(false);

  const redirectAfterAuth = async () => {
    try {
      const connections = (await api.get("/platforms")) as { id: string }[];
      if (!connections || connections.length === 0) {
        router.push("/onboarding");
      } else {
        router.push("/overview");
      }
    } catch {
      router.push("/overview");
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = (await api.post("/auth/login", {
        email: loginEmail,
        password: loginPassword,
      })) as AuthResponse;
      login(data.token, data.refresh_token || "", {
        user_id: data.user_id,
        name: data.name,
        email: data.email,
        role: data.role,
      });
      await redirectAfterAuth();
    } catch (err) {
      setError(typeof err === "string" ? err : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = (await api.post("/auth/register", {
        email: regEmail,
        password: regPassword,
        name: regName,
      })) as AuthResponse;
      login(data.token, data.refresh_token || "", {
        user_id: data.user_id,
        name: data.name,
        email: data.email,
        role: data.role,
      });
      await redirectAfterAuth();
    } catch (err) {
      setError(typeof err === "string" ? err : "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSuccess = async (credentialResponse: { credential?: string }) => {
    if (!credentialResponse.credential) return;
    setLoading(true);
    setError("");
    try {
      const data = (await api.post("/auth/google", {
        credential: credentialResponse.credential,
      })) as AuthResponse;
      login(data.token, data.refresh_token || "", {
        user_id: data.user_id,
        name: data.name,
        email: data.email,
        role: data.role,
      });
      await redirectAfterAuth();
    } catch (err) {
      setError(typeof err === "string" ? err : "Google login failed");
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/auth/forgot-password", { email: forgotEmail });
      setForgotSent(true);
    } catch {
      setForgotSent(true);
    } finally {
      setLoading(false);
    }
  };

  const formCard = (content: React.ReactNode) => (
    <div className="min-h-screen flex">
      {/* Left panel — branding */}
      <div className="hidden lg:flex lg:w-[480px] bg-[#0B1929] relative overflow-hidden flex-col justify-between p-10">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-indigo-600/10 blur-[100px] rounded-full pointer-events-none" />
        <div className="relative">
          <Link href="/" className="flex items-center gap-2 text-white font-extrabold text-xl tracking-tight mb-12">
            <DollarSign className="h-6 w-6 text-indigo-400" />
            costly
          </Link>
          <h2 className="text-3xl font-extrabold text-white tracking-tight leading-tight mb-4">
            See every dollar your<br />
            <span className="bg-gradient-to-r from-indigo-400 via-violet-400 to-purple-400 bg-clip-text text-transparent">data stack costs</span>
          </h2>
          <p className="text-slate-400 leading-relaxed mb-10">
            Connect 15+ platforms in minutes. Get unified cost intelligence across warehouses, pipelines, BI, AI, and CI/CD.
          </p>
          <div className="space-y-4">
            {[
              { icon: BarChart3, text: "Unified cost dashboard across all platforms" },
              { icon: Bot, text: "AI agent answers cost questions in plain English" },
              { icon: Sparkles, text: "Smart recommendations with projected savings" },
            ].map(({ icon: Icon, text }) => (
              <div key={text} className="flex items-center gap-3">
                <div className="h-8 w-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center shrink-0">
                  <Icon className="h-4 w-4 text-indigo-400" />
                </div>
                <span className="text-sm text-slate-300">{text}</span>
              </div>
            ))}
          </div>
        </div>
        <p className="relative text-xs text-slate-600">
          100% read-only. No data extraction. Open-source connectors.
        </p>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center p-6 bg-[#FAFBFC]">
        <div className="w-full max-w-[420px]">
          {/* Mobile logo */}
          <div className="lg:hidden flex items-center justify-center gap-2 mb-8">
            <Link href="/" className="flex items-center gap-2 text-slate-900 font-extrabold text-xl tracking-tight">
              <DollarSign className="h-6 w-6 text-indigo-500" />
              costly
            </Link>
          </div>
          {content}
        </div>
      </div>
    </div>
  );

  if (showForgot) {
    return formCard(
      <div>
        <button
          onClick={() => { setShowForgot(false); setForgotSent(false); }}
          className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 mb-6 transition"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to sign in
        </button>
        <h1 className="text-2xl font-bold text-slate-900 mb-1">Reset password</h1>
        <p className="text-sm text-slate-500 mb-6">
          Enter your email and we&apos;ll send you a reset link.
        </p>
        {forgotSent ? (
          <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg">
            <p className="text-sm text-emerald-700">
              If that email is registered, you&apos;ll receive a reset link shortly.
            </p>
          </div>
        ) : (
          <form onSubmit={handleForgotPassword} className="space-y-4">
            <div>
              <Label htmlFor="forgot-email" className="text-slate-700">Email</Label>
              <Input
                id="forgot-email"
                type="email"
                placeholder="you@company.com"
                value={forgotEmail}
                onChange={(e) => setForgotEmail(e.target.value)}
                required
                className="mt-1.5 h-11"
              />
            </div>
            <Button type="submit" className="w-full h-11 bg-indigo-600 hover:bg-indigo-700" disabled={loading}>
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Send Reset Link
            </Button>
          </form>
        )}
      </div>
    );
  }

  return formCard(
    <div>
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Welcome back</h1>
      <p className="text-sm text-slate-500 mb-6">
        Sign in to your account or create a new one.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
          {error}
        </div>
      )}

      <div className="mb-6 flex justify-center">
        <GoogleLogin
          onSuccess={handleGoogleSuccess}
          onError={() => setError("Google login failed")}
          width={380}
        />
      </div>

      <div className="relative mb-6">
        <div className="absolute inset-0 flex items-center">
          <span className="w-full border-t border-slate-200" />
        </div>
        <div className="relative flex justify-center text-xs uppercase">
          <span className="bg-[#FAFBFC] px-3 text-slate-400 font-medium">Or continue with email</span>
        </div>
      </div>

      <Tabs defaultValue="signin">
        <TabsList className="grid w-full grid-cols-2 mb-5 bg-slate-100">
          <TabsTrigger value="signin">Sign In</TabsTrigger>
          <TabsTrigger value="register">Register</TabsTrigger>
        </TabsList>

        <TabsContent value="signin">
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <Label htmlFor="login-email" className="text-slate-700">Email</Label>
              <Input
                id="login-email"
                type="email"
                placeholder="you@company.com"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                required
                className="mt-1.5 h-11"
              />
            </div>
            <div>
              <Label htmlFor="login-password" className="text-slate-700">Password</Label>
              <Input
                id="login-password"
                type="password"
                placeholder="Enter your password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                required
                className="mt-1.5 h-11"
              />
            </div>
            <Button type="submit" className="w-full h-11 bg-indigo-600 hover:bg-indigo-700" disabled={loading}>
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Sign In
            </Button>
            <button
              type="button"
              className="w-full text-center text-sm text-slate-500 hover:text-indigo-600 transition"
              onClick={() => setShowForgot(true)}
            >
              Forgot password?
            </button>
          </form>
        </TabsContent>

        <TabsContent value="register">
          <form onSubmit={handleRegister} className="space-y-4">
            <div>
              <Label htmlFor="reg-name" className="text-slate-700">Full Name</Label>
              <Input
                id="reg-name"
                placeholder="Jane Smith"
                value={regName}
                onChange={(e) => setRegName(e.target.value)}
                required
                className="mt-1.5 h-11"
              />
            </div>
            <div>
              <Label htmlFor="reg-email" className="text-slate-700">Email</Label>
              <Input
                id="reg-email"
                type="email"
                placeholder="you@company.com"
                value={regEmail}
                onChange={(e) => setRegEmail(e.target.value)}
                required
                className="mt-1.5 h-11"
              />
            </div>
            <div>
              <Label htmlFor="reg-password" className="text-slate-700">Password</Label>
              <Input
                id="reg-password"
                type="password"
                placeholder="At least 8 characters"
                value={regPassword}
                onChange={(e) => setRegPassword(e.target.value)}
                required
                minLength={8}
                className="mt-1.5 h-11"
              />
            </div>
            <Button type="submit" className="w-full h-11 bg-indigo-600 hover:bg-indigo-700" disabled={loading}>
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Create Account
            </Button>
          </form>
        </TabsContent>
      </Tabs>
    </div>
  );
}
