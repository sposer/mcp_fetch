import unittest
from mcp_fetch.cleaner import clean_html

class TestCleaner(unittest.TestCase):
    def test_basic_cleaning(self):
        html = """
        <html>
        <body>
            <header>Header</header>
            <div id="main">
                <h1>Title</h1>
                <p>Content</p>
                <div class="sidebar">Sidebar</div>
                <div class="ads">Ad</div>
            </div>
            <footer>Footer</footer>
        </body>
        </html>
        """
        cleaned = clean_html(html)
        self.assertNotIn("Header", cleaned)
        self.assertNotIn("Footer", cleaned)
        self.assertNotIn("Sidebar", cleaned)
        self.assertNotIn("Ad", cleaned)
        self.assertIn("Title", cleaned)
        self.assertIn("Content", cleaned)

    def test_zhihu_simulation(self):
        # Simulation of a Zhihu-like structure
        html = """
        <div class="ColumnPageHeader-Wrapper">Header</div>
        <div class="Post-NormalMain">
            <div class="Post-Header"><h1>Article Title</h1></div>
            <div class="Post-RichText">
                <p>This is the main article content.</p>
            </div>
            <div class="Post-SideBar">
                <div class="Card">Author Info</div>
                <div class="Card">Related Posts</div>
            </div>
            <div class="Recommendations-Main">
                <h2>Recommended</h2>
                <ul><li>Link 1</li></ul>
            </div>
        </div>
        <div class="CornerButtons">Buttons</div>
        """
        cleaned = clean_html(html)
        
        # Should remove
        self.assertNotIn("ColumnPageHeader-Wrapper", cleaned)
        self.assertNotIn(">Header<", cleaned) # The content of the top header
        self.assertNotIn("Author Info", cleaned)
        self.assertNotIn("Related Posts", cleaned)
        self.assertNotIn("Recommended", cleaned)
        self.assertNotIn("Buttons", cleaned)
        
        # Should keep
        self.assertIn("Post-Header", cleaned) # Class name should exist
        self.assertIn("Article Title", cleaned)
        self.assertIn("main article content", cleaned)

    def test_zhihu_specific_garbage(self):
        # Test case based on user's report of lingering garbage
        html = """
        <div class="AppHeader">Top Nav</div>
        <div class="GlobalSideBar">
            <div class="Card">
                <div class="Card-header">Hot Search</div>
                <div class="HotList">
                    <a href="search?q=hot">Hot Topic 1</a>
                    <a href="search?q=trending">Trending Topic</a>
                </div>
            </div>
            <div class="Card">
                <div class="CreatorEntrance">
                    <a href="/creator">Write an answer</a>
                </div>
            </div>
        </div>
        
        <div class="Post-NormalMain">
            <div class="Post-Content">
                <p>Real Content</p>
            </div>
            
            <div class="Post-topics-wrapper">
                <a href="//www.zhihu.com/topic/19652110">自动更新</a>
                <a href="//www.zhihu.com/topic/19552612">Microsoft Windows</a>
            </div>
        </div>

        <div class="SignFlowModal">
            <div class="SignFlow">
                <img src="https://static.zhihu.com/liukanshan.png">
                <span>登录即可查看</span>
            </div>
        </div>
        
        <div class="Footer">
            <a href="mailto:jobs@zhihu.com">想来知乎工作？请发送邮件</a>
        </div>
        
        <a href="https://click.aliyun.com/m/1000" class="internal-ad">Aliyun Ad</a>
        """
        cleaned = clean_html(html)
        
        # Should remove
        self.assertNotIn("AppHeader", cleaned)
        self.assertNotIn("Top Nav", cleaned)
        self.assertNotIn("GlobalSideBar", cleaned)
        self.assertNotIn("Hot Search", cleaned)
        self.assertNotIn("Hot Topic 1", cleaned)
        self.assertNotIn("SignFlow", cleaned)
        self.assertNotIn("登录即可查看", cleaned)
        self.assertNotIn("想来知乎工作", cleaned)
        self.assertNotIn("Aliyun Ad", cleaned) # Should be caught by ad/promo logic if class matches or parent matches
        
        # Should keep
        self.assertIn("Real Content", cleaned)

if __name__ == "__main__":
    unittest.main()
