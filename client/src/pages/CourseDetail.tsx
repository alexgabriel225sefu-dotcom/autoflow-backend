import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { CheckCircle, Lock, Play, Download } from 'lucide-react';

export function CourseDetail() {
  const [currentLesson, setCurrentLesson] = useState(0);
  const [completed, setCompleted] = useState<number[]>([]);

  const course = {
    title: 'AI Marketing Masterclass',
    description: 'Learn how to build a 6-7 figure AI business',
    lessons: [
      {
        id: 1,
        title: 'Introduction to AI Marketing',
        duration: '15 min',
        video: 'https://example.com/lesson1.mp4',
        content: `
          In this lesson, you'll learn:
          - What AI marketing is and why it matters
          - How to leverage AI tools for massive growth
          - Real case studies of 6-7 figure businesses
          - Your roadmap to success
        `,
        quiz: [
          {
            question: 'What is the primary benefit of AI marketing?',
            options: ['Automation', 'Cost reduction', 'Scale', 'All of the above'],
            correct: 3,
          },
        ],
      },
      {
        id: 2,
        title: 'Social Media Automation',
        duration: '20 min',
        video: 'https://example.com/lesson2.mp4',
        content: `
          Learn how to:
          - Schedule posts across all platforms
          - Generate AI captions
          - Analyze engagement metrics
          - Build a content calendar
        `,
        quiz: [
          {
            question: 'How many posts should you schedule per week?',
            options: ['1-2', '3-5', '7-10', 'Depends on niche'],
            correct: 3,
          },
        ],
      },
      {
        id: 3,
        title: 'Email Marketing Mastery',
        duration: '25 min',
        video: 'https://example.com/lesson3.mp4',
        content: `
          Master email marketing:
          - Build high-converting email sequences
          - Write subject lines that get opened
          - Segment your audience
          - Automate your sales funnel
        `,
        quiz: [
          {
            question: 'What is the average email open rate?',
            options: ['5%', '15%', '25%', '35%'],
            correct: 1,
          },
        ],
      },
    ],
  };

  const lesson = course.lessons[currentLesson];
  const isCompleted = completed.includes(lesson.id);

  const completeLesson = () => {
    if (!isCompleted) {
      setCompleted([...completed, lesson.id]);
    }
    if (currentLesson < course.lessons.length - 1) {
      setCurrentLesson(currentLesson + 1);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 py-8 px-4">
      <div className="max-w-6xl mx-auto grid md:grid-cols-4 gap-8">
        {/* Sidebar */}
        <div className="md:col-span-1">
          <Card className="bg-slate-800 border-slate-700 p-4 space-y-4">
            <h3 className="font-bold text-white">{course.title}</h3>
            <div className="space-y-2">
              {course.lessons.map((l, i) => (
                <button
                  key={l.id}
                  onClick={() => setCurrentLesson(i)}
                  className={`w-full text-left p-3 rounded-lg transition-all ${
                    currentLesson === i
                      ? 'bg-amber-500/20 border border-amber-500/50'
                      : 'bg-slate-700 hover:bg-slate-600'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {completed.includes(l.id) ? (
                      <CheckCircle className="w-4 h-4 text-green-500" />
                    ) : (
                      <div className="w-4 h-4 rounded-full border border-slate-500" />
                    )}
                    <span className="text-sm">{l.title}</span>
                  </div>
                </button>
              ))}
            </div>
          </Card>
        </div>

        {/* Main Content */}
        <div className="md:col-span-3 space-y-6">
          {/* Video Player */}
          <Card className="bg-slate-800 border-slate-700 overflow-hidden">
            <div className="aspect-video bg-slate-900 flex items-center justify-center">
              <div className="text-center space-y-4">
                <Play className="w-16 h-16 text-amber-500 mx-auto" />
                <p className="text-slate-400">Video Player</p>
                <p className="text-sm text-slate-500">{lesson.duration}</p>
              </div>
            </div>
          </Card>

          {/* Lesson Content */}
          <Card className="bg-slate-800 border-slate-700 p-6 space-y-4">
            <h2 className="text-2xl font-bold text-white">{lesson.title}</h2>
            <div className="prose prose-invert max-w-none">
              <p className="text-slate-300 whitespace-pre-wrap">{lesson.content}</p>
            </div>
          </Card>

          {/* Quiz */}
          <Card className="bg-slate-800 border-slate-700 p-6 space-y-4">
            <h3 className="text-xl font-bold text-white">Lesson Quiz</h3>
            {lesson.quiz.map((q, i) => (
              <div key={i} className="space-y-3">
                <p className="text-white font-medium">{q.question}</p>
                <div className="space-y-2">
                  {q.options.map((option, j) => (
                    <button
                      key={j}
                      className="w-full text-left p-3 rounded-lg bg-slate-700 hover:bg-slate-600 transition-all text-slate-300"
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </Card>

          {/* Actions */}
          <div className="flex gap-4">
            <Button
              onClick={completeLesson}
              className="flex-1 bg-amber-500 hover:bg-amber-600 text-black font-bold"
            >
              {isCompleted ? 'Continue to Next' : 'Mark as Complete'}
            </Button>
            <Button variant="outline" className="flex-1">
              <Download className="w-4 h-4 mr-2" />
              Download Materials
            </Button>
          </div>

          {/* Progress */}
          <div className="bg-slate-800 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-slate-300">Course Progress</span>
              <span className="text-amber-400 font-bold">
                {completed.length}/{course.lessons.length}
              </span>
            </div>
            <div className="w-full bg-slate-700 rounded-full h-2">
              <div
                className="bg-amber-500 h-2 rounded-full transition-all"
                style={{ width: `${(completed.length / course.lessons.length) * 100}%` }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
