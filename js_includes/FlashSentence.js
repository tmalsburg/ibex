/* This software is licensed under a BSD license; see the LICENSE file for details. */

(function () {
var soundId = 0;

define_ibex_controller({
name: "FlashSentence",

jqueryWidget: {
    _init: function () {
        var self = this;
        self.cssPrefix = self.options._cssPrefix;

        var $loading;
        var doneLoading = false;
        if (typeof(self.options.s) != "string") {
            if (self.options.s.audio) {
                if (self.options.audioMessage) {
                    self.element.append($loading = $("<div>").addClass(self.cssPrefix + 'loading'));
                    setTimeout(function () {
                        if (! doneLoading)
                            $loading.text(conf_loadingMessage);
                    }, 250);
                }
                withSoundManager(completeInit);
            }
            else {
                self.sentenceDom = htmlCodeToDOM(self.options.s)
                completeInit();
            }
        }
        else {
            self.sentenceDom = $("<div>").text(self.options.s);
            completeInit();
        }

        function completeInit(sm) {
            if (sm) {
                if (self.options.audioMessage) {
                    if (typeof(self.options.audioMessage) != "string")
                        self.sentenceDom = htmlCodeToDOM(self.options.audioMessage);
                    else
                        self.sentenceDom = $("<div>").text(self.options.audioMessage);
                }
                var name = self.options.s.audio;
                var url = __server_py_script_name__ + '?resource=' + escape(name);
                self.sid = soundId++;
                sm.createSound('sound' + self.sid, url);

                if (self.options.audioTrigger == "click") {
                    self.sentenceDom.css('cursor', 'pointer');
                    self.sentenceDom.click(function () {
                        sm.play('sound' + self.sid);
                    });
                }
                else { // Immediate
                    sm.play('sound' + self.sid);
                }
            }

            self.finishedCallback = self.options._finishedCallback;
            self.utils = self.options._utils;
        
            self.timeout = dget(self.options, "timeout", 2000);

            self.sentenceDescType = dget(self.options, "sentenceDescType", "literal");
            assert(self.sentenceDescType == "md5" || self.sentenceDescType == "literal", "Bad value for 'sentenceDescType' option of FlashSentence controller.");
            if (self.sentenceDescType == "md5") {
                alert("'md5' value no longer supported for 'sentenceDescType' option of FlashSentence controller");
                throw "Bad option to FlashSentence";
            }
            else {
                self.sentenceMD5 = csv_url_encode(self.options.s.html ? self.options.s.html : (self.options.s.audio ? self.options.s.audio : (self.options.s+'')));
            }

            self.element.addClass(self.cssPrefix + "flashed-sentence");
            if (self.sentenceDom) {
                if ($loading) {
                    doneLoading = true;
                    $loading.replaceWith(self.sentenceDom)
                }
                else
                    self.element.append(self.sentenceDom);
            }

            if (self.timeout) {
                var t = this;
                self.utils.setTimeout(function() {
                    t.finishedCallback([[["Sentence (or sentence MD5)", t.sentenceMD5]]]);
                }, self.timeout);
            }
            else {
                // Give results without actually finishing.
                if (self.utils.setResults)
                    self.utils.setResults([[["Sentence (or sentence MD5)", self.sentenceMD5]]]);
            }
        }
    }
},

properties: {
    obligatory: ["s"],
    htmlDescription: function (opts) {
        return $(document.createElement("div")).text(opts.s)[0];
    }
}
});

})();
