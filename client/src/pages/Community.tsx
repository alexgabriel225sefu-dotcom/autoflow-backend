import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { MessageCircle, Heart, Share2, Users } from 'lucide-react';
import { toast } from 'sonner';

export function Community() {
  const [posts, setPosts] = useState([
    {
      id: 1,
      author: 'John Doe',
      avatar: '👨',
      title: 'Just hit $10K MRR with AICashSystem!',
      content: 'Used the social media scheduler to automate my Twitter growth...',
      likes: 234,
      replies: 45,
      timestamp: '2 hours ago',
    },
    {
      id: 2,
      author: 'Jane Smith',
      avatar: '👩',
      title: 'Email marketing tips that actually work',
      content: 'Here are the 5 email templates that generated $50K in sales...',
      likes: 567,
      replies: 89,
      timestamp: '4 hours ago',
    },
  ]);

  const [newPost, setNewPost] = useState('');
  const [newTitle, setNewTitle] = useState('');

  const createPost = () => {
    if (!newTitle.trim() || !newPost.trim()) {
      toast.error('Fill all fields');
      return;
    }

    setPosts([
      {
        id: Date.now(),
        author: 'You',
        avatar: '🧑',
        title: newTitle,
        content: newPost,
        likes: 0,
        replies: 0,
        timestamp: 'now',
      },
      ...posts,
    ]);

    setNewTitle('');
    setNewPost('');
    toast.success('Post created!');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Community</h1>
        <p className="text-muted-foreground">Join 10K+ entrepreneurs sharing strategies</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          {/* Create Post */}
          <Card>
            <CardHeader>
              <CardTitle>Share Your Success</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                placeholder="Post title..."
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
              <Textarea
                placeholder="What's your story? Share tips, wins, or questions..."
                value={newPost}
                onChange={(e) => setNewPost(e.target.value)}
                rows={4}
              />
              <Button onClick={createPost} className="w-full">
                Post to Community
              </Button>
            </CardContent>
          </Card>

          {/* Posts Feed */}
          {posts.map(post => (
            <Card key={post.id}>
              <CardContent className="p-6 space-y-4">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{post.avatar}</span>
                  <div>
                    <p className="font-medium">{post.author}</p>
                    <p className="text-sm text-muted-foreground">{post.timestamp}</p>
                  </div>
                </div>

                <div>
                  <h3 className="font-bold text-lg">{post.title}</h3>
                  <p className="text-muted-foreground mt-2">{post.content}</p>
                </div>

                <div className="flex gap-4 pt-4 border-t">
                  <button className="flex items-center gap-2 text-muted-foreground hover:text-foreground">
                    <Heart className="w-4 h-4" />
                    <span className="text-sm">{post.likes}</span>
                  </button>
                  <button className="flex items-center gap-2 text-muted-foreground hover:text-foreground">
                    <MessageCircle className="w-4 h-4" />
                    <span className="text-sm">{post.replies}</span>
                  </button>
                  <button className="flex items-center gap-2 text-muted-foreground hover:text-foreground">
                    <Share2 className="w-4 h-4" />
                  </button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="w-5 h-5" />
                Community Stats
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-sm text-muted-foreground">Active Members</p>
                <p className="text-2xl font-bold">10,234</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Posts This Week</p>
                <p className="text-2xl font-bold">1,456</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Total Engagement</p>
                <p className="text-2xl font-bold">45.2K</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Top Contributors</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {['🏆 Alex Chen', '🥈 Sarah Johnson', '🥉 Mike Davis'].map((name, i) => (
                <p key={i} className="text-sm">{name}</p>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export function Courses() {
  const [courses] = useState([
    {
      id: 1,
      title: 'AI Marketing Masterclass',
      progress: 65,
      lessons: 12,
      completed: 8,
    },
    {
      id: 2,
      title: 'Automation Secrets',
      progress: 30,
      lessons: 10,
      completed: 3,
    },
  ]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Courses</h1>
        <p className="text-muted-foreground">Learn from industry experts</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {courses.map(course => (
          <Card key={course.id}>
            <CardHeader>
              <CardTitle>{course.title}</CardTitle>
              <CardDescription>
                {course.completed}/{course.lessons} lessons completed
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-600 h-2 rounded-full"
                  style={{ width: `${course.progress}%` }}
                />
              </div>
              <p className="text-sm text-muted-foreground">{course.progress}% complete</p>
              <Button className="w-full">
                {course.progress === 100 ? 'View Certificate' : 'Continue Learning'}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
