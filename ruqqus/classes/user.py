from werkzeug.security import generate_password_hash, check_password_hash
from flask import render_template, session
from time import strftime, time, gmtime
from sqlalchemy import *
from sqlalchemy.orm import relationship
import hmac
from os import environ
from secrets import token_hex

from ruqqus.helpers.base36 import *
from ruqqus.helpers.security import *
from .votes import Vote
from .ips import IP
from ruqqus.__main__ import Base, db

class User(Base):

    __tablename__="users"
    id = Column(Integer, primary_key=True)
    username = Column(String, default=None)
    email = Column(String, default=None)
    passhash = Column(String, default=None)
    created_utc = Column(BigInteger, default=0)
    admin_level = Column(Integer, default=0)
    is_banned = Column(Boolean, default=False)
    is_activated = Column(Boolean, default=False)
    username_verified = Column(Boolean, default=False)
    over_18=Column(Boolean, default=False)
    creation_ip=Column(String, default=None)
    most_recent_ip=Column(String, default=None)
    submissions=relationship("Submission", lazy="dynamic", backref="users")
    votes=relationship("Vote", lazy="dynamic", backref="users")
    ips = relationship('IP', lazy="dynamic", backref="users")

    def __init__(self, **kwargs):

        if "password" in kwargs:

            kwargs["passhash"]=self.hash_password(kwargs["password"])
            kwargs.pop("password")

        kwargs["created_utc"]=int(time())
        kwargs["activehash"]=self.activation_hash(self.username)

        super().__init__(**kwargs)

    def _lazy(f):

        def wrapper(self, *args, **kwargs):

            if "_lazy_dict" not in self.__dict__:
                self._lazy_dict={}

            if f.__name__ not in self._lazy_dict:
                self._lazy_dict[f.__name__]=f(self, *args, **kwargs)

            return self._lazy_dict[f.__name__]

        wrapper.__name__=f.__name__
        return wrapper

    @property
    @_lazy
    def energy(self):

        posts=db.query(relationship("Submission")).filter_by(is_banned=False).all()

        return sum([x.score for x in self.posts])

    @property
    @_lazy
    def base36id(self):
        return base36encode(self.id)

    @property
    @_lazy
    def fullname(self):
        return f"t1_{self.base36id}"

    def vote_status_on_post(self, post):

        vote = [x for x in self.votes if x.submission_id==post.id]
        if not vote:
            return 0
          
        vote=vote[0]
        
        return vote.vote_type

    def update_ip(self, remote_addr):
        
        if not remote_addr==self.most_recent_ip:
            self.most_recent_ip = remote_addr
            db.add(self)

        if not remote_addr in [i.ip for i in self.ips]:
            db.add(IP(user_id=self.id, ip=remote_addr))
        
        if db.dirty:
            db.commit()

    def activation_hash(self):
        return generate_password_hash(self.username, method='pbkdf2:sha256', salt_length=8)

    def hash_password(self, password):
        return generate_password_hash(password, method='pbkdf2:sha512', salt_length=8)

    def verifyPass(self, password):
        return check_password_hash(self.passhash, password)

    @property
    def visible_posts(self):
        return db.query(Base.metadata.tables['Submission']).filter_by(is_banned=False).all()
    
    def rendered_userpage(self, v=None):

        if self.is_banned:
            return render_template("userpage_banned.html", u=self, v=v)
        
        posts = self.visible_posts
        posts.sort(key=lambda x: x.created_utc, reverse=True)
        
        if len(posts)>50:
            posts=posts[0:50]

        posts.sort(key=lambda x: x.created_utc, reverse=True)

        return render_template("userpage.html", u=self, v=v, listing=posts)

    @property
    @_lazy
    def formkey(self):

        if "session_id" not in session:
            session["session_id"]=token_hex(16)

        msg=f"{session['session_id']}{self.id}"

        return generate_hash(msg)

    def validate_formkey(self, formkey):

        return validate_hash(f"{session['session_id']}{self.id}", formkey)
    
    def verify_username(self, username):
        
        #no reassignments allowed
        if self.username_verified:
            return render_template("settings.html", v=self, error="Your account has already validated its username.")
        
        #For use when verifying username with reddit
        #Set username. Randomize username of any other existing account with same
        try:
            existing = db.query(User).filter_by(username=username).all()[0]

            #No reassignments allowed
            if existing.username_verified:
                return render_template("settings.html", v=self, error="Another account has already validated that username.")
                
            # Rename new account to user_id
            # guaranteed to be unique
            existing.username=f"user_{existing.id}"
            
            db.add(existing)
            db.commit()
                                     
        except IndexError:
            pass
                                      
        self.username=username
        self.username_verified=True
        
        db.add(self)
        db.commit()

        return render_template("settings.html", v=self, msg="Your account name has been updated and validated.")

    @property
    @_lazy
    def url(self):
        return f"/u/{self.username}"

    @property
    @_lazy
    def created_date(self):

        print(self.created_utc)

        return strftime("%d %B %Y", gmtime(self.created_utc))

    def __repr__(self):
        return f"<User(username={self.username})>"
