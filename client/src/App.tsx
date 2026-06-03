import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Switch } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import Home from "./pages/Home";
import BotBuilder from "./pages/BotBuilder";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import Alerts from "./pages/Alerts";
import { PremiumLanding } from "./pages/PremiumLanding";
import { SocialMediaScheduler } from "./pages/tools/SocialMediaScheduler";
import { EmailMarketing } from "./pages/tools/EmailMarketing";
import { ContentCreation } from "./pages/tools/ContentCreation";
import { AIAutomation, LeadGeneration } from "./pages/tools/AIAutomation";
import { Community, Courses } from "./pages/Community";
import { Affiliate } from "./pages/Affiliate";
import { PrivacyPolicy } from "./pages/PrivacyPolicy";
import { TermsOfService } from "./pages/TermsOfService";
import { CheckoutSuccess, CheckoutCancel } from "./pages/CheckoutSuccess";
import { CourseDetail } from "./pages/CourseDetail";
import { EmailCapture } from "./pages/EmailCapture";

function Router() {
  return (
    <Switch>
      <Route path="" component={PremiumLanding} />
      <Route path="/home" component={Home} />
      <Route path="/builder" component={BotBuilder} />
      <Route path="/dashboard" component={Dashboard} />
      <Route path="/settings" component={Settings} />
      <Route path="/alerts" component={Alerts} />
      
      {/* AICashSystem Tools */}
      <Route path="/tools/social-media" component={SocialMediaScheduler} />
      <Route path="/tools/email" component={EmailMarketing} />
      <Route path="/tools/content" component={ContentCreation} />
      <Route path="/tools/automation" component={AIAutomation} />
      <Route path="/tools/leads" component={LeadGeneration} />
      
      {/* Community & Education */}
      <Route path="/community" component={Community} />
      <Route path="/courses" component={Courses} />
      
      {/* Affiliate */}
      <Route path="/affiliate" component={Affiliate} />
      
      {/* Legal */}
      <Route path="/privacy" component={PrivacyPolicy} />
      <Route path="/terms" component={TermsOfService} />
      
      {/* Checkout */}
      <Route path="/checkout/success" component={CheckoutSuccess} />
      <Route path="/checkout/cancel" component={CheckoutCancel} />
      
      {/* Course */}
      <Route path="/course/:id" component={CourseDetail} />
      
      {/* Email */}
      <Route path="/email-capture" component={EmailCapture} />
      
      <Route path="/404" component={NotFound} />
      {/* Final fallback route */}
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider
        defaultTheme="dark"
      >
        <TooltipProvider>
          <Toaster />
          <Router />
        </TooltipProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
